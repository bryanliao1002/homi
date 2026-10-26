from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.ai_service import AI_MODEL, AIServiceError
from backend.mediation_agents import (
    AGENT_VERSION,
    AGREEMENT_AGENT,
    AgentOutputError,
    LISTENING_AGENT,
    MEDIATION_AGENT,
    draft_agreement,
    listen,
    mediate,
)
from backend.main import database, new_id, now_iso, require_household_member


router = APIRouter()
CASE_CATEGORIES = (
    "Dishes & cleanliness",
    "Chores",
    "Noise & quiet",
    "Guests",
    "Shared spaces",
    "Shared items",
    "Other",
)
SAFETY_GUIDANCE = (
    "This may be more serious than an everyday roommate disagreement, so Little Homi has paused AI mediation. "
    "If anyone is in immediate danger, contact local emergency services now. Consider reaching out to someone you trust "
    "or a local support service. You do not need to continue or share more here."
)
_SAFETY_PATTERN = re.compile(
    r"\b(?:threat(?:en(?:ed|ing|s)?)?|hit me|hurt me|afraid (?:of|that)|feel unsafe|not safe|"
    r"physical(?:ly)? (?:hurt|harm)|abuse|assault|stalking|domestic violence|in immediate danger|"
    r"weapon|kill you|kill me|forced me)\b",
    re.IGNORECASE,
)
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")
MAX_CASE_STATEMENT_CHARACTERS = 8_000
_STOP_WORDS = {"about", "after", "again", "could", "every", "from", "have", "into", "just", "like", "more", "other", "roommate", "shared", "that", "their", "there", "these", "they", "this", "those", "want", "what", "when", "would", "with", "your"}


class MediationCreate(BaseModel):
    member_id: str
    other_member_ids: list[str] = Field(min_length=1, max_length=7)
    category: str = Field(min_length=2, max_length=40)
    statement: str = Field(min_length=20, max_length=4_000)
    hide_identity: bool = False
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=100)

    @field_validator("category")
    @classmethod
    def valid_category(cls, value: str) -> str:
        value = value.strip()
        if value not in CASE_CATEGORIES:
            raise ValueError("Choose a supported disagreement topic")
        return value

    @field_validator("statement")
    @classmethod
    def clean_statement(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 20:
            raise ValueError("Please share at least 20 characters so the concern is clear")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not _IDEMPOTENCY_PATTERN.fullmatch(value):
            raise ValueError("Invalid request key")
        return value

    @model_validator(mode="after")
    def unique_roommates(self):
        if self.member_id in self.other_member_ids or len(set(self.other_member_ids)) != len(self.other_member_ids):
            raise ValueError("Choose each other roommate only once")
        return self


class StatementSubmit(BaseModel):
    member_id: str
    statement: str = Field(min_length=20, max_length=4_000)

    @field_validator("statement")
    @classmethod
    def clean_statement(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 20:
            raise ValueError("Please share at least 20 characters so the concern is clear")
        return value


class ClarificationSubmit(BaseModel):
    member_id: str
    answer: str = Field(default="", max_length=600)
    mark_unknown: bool = False

    @model_validator(mode="after")
    def answer_or_unknown(self):
        self.answer = self.answer.strip()
        if self.mark_unknown and self.answer:
            raise ValueError("Choose either an answer or ‘I’m not sure’")
        if not self.mark_unknown and len(self.answer) < 5:
            raise ValueError("Add a short answer or mark this as unknown")
        return self


class MemberAction(BaseModel):
    member_id: str


class AgreementDecision(BaseModel):
    member_id: str
    decision: Literal["approve", "reject", "request_changes"]
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_change_note(self):
        if self.decision == "request_changes" and len(self.note) < 10:
            raise ValueError("Add at least 10 characters describing the requested change")
        return self


def _table_rows(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(sql, params)]


def _member_for_household(db: sqlite3.Connection, household_id: str, member_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT id, name, color FROM members WHERE household_id = ? AND id = ?",
        (household_id, member_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Household or roommate not found")
    return dict(row)


def _case_access(db: sqlite3.Connection, household_id: str, case_id: str, member_id: str) -> dict[str, Any]:
    case = db.execute(
        "SELECT * FROM mediation_cases WHERE id = ? AND household_id = ?",
        (case_id, household_id),
    ).fetchone()
    if case is None:
        raise HTTPException(status_code=404, detail="Mediation case not found")
    participant = db.execute(
        "SELECT 1 FROM mediation_participants WHERE case_id = ? AND member_id = ?",
        (case_id, member_id),
    ).fetchone()
    if participant is None:
        raise HTTPException(status_code=403, detail="Only roommates involved in this case can view or respond")
    return dict(case)


def _participant_rows(db: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    return _table_rows(
        db,
        """SELECT p.member_id, p.ordinal, m.name, m.color
           FROM mediation_participants p JOIN members m ON m.id = p.member_id
           WHERE p.case_id = ? ORDER BY p.ordinal""",
        (case_id,),
    )


def _perspectives(db: sqlite3.Connection, case: dict[str, Any]) -> list[dict[str, str]]:
    people = _participant_rows(db, case["id"])
    statements = {
        row["member_id"]: row["body"]
        for row in db.execute("SELECT member_id, body FROM mediation_statements WHERE case_id = ?", (case["id"],))
    }
    return [
        {"participant_id": f"p{person['ordinal'] + 1}", "perspective": statements[person["member_id"]]}
        for person in people
        if person["member_id"] in statements
    ]


def _run_start(case_id: str, agent: str, operation: str, effort: str, input_count: int) -> str:
    run_id = new_id()
    with database() as db:
        db.execute(
            """INSERT INTO mediation_agent_runs
               (run_id, case_id, agent_name, agent_version, operation, model,
                reasoning_effort, input_count, started_at, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
            (run_id, case_id, agent, AGENT_VERSION, operation, AI_MODEL, effort, input_count, now_iso()),
        )
    return run_id


def _trace(run_id: str, event: str, tool_name: str | None, **safe_detail: Any) -> None:
    allowed = {"input_count", "output_count", "record_count", "rule_count", "agreement_count", "question_count", "participant_count", "status", "reasoning_effort", "attempt"}
    detail = {key: value for key, value in safe_detail.items() if key in allowed and isinstance(value, (str, int, float, bool, type(None)))}
    with database() as db:
        sequence = db.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM mediation_agent_traces WHERE run_id = ?", (run_id,)).fetchone()[0]
        db.execute(
            """INSERT INTO mediation_agent_traces
               (run_id, sequence, event, tool_name, safe_detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, sequence, event[:80], tool_name[:80] if tool_name else None, json.dumps(detail), now_iso()),
        )


def _run_finish(run_id: str, *, output: Any = None, error_code: str | None = None) -> None:
    response = getattr(output, "result", None)
    with database() as db:
        row = db.execute("SELECT started_at FROM mediation_agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        started = row[0] if row else None
        try:
            parsed = datetime.fromisoformat(started) if started else None
            latency_ms = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds() * 1000)) if parsed else 0
        except (TypeError, ValueError):
            latency_ms = 0
        db.execute(
            """UPDATE mediation_agent_runs SET completed_at = ?, latency_ms = ?, outcome = ?,
               input_tokens = ?, output_tokens = ?, reasoning_tokens = ?, request_id = ?, error_code = ?
               WHERE run_id = ?""",
            (
                now_iso(), latency_ms, "success" if response else "error",
                getattr(response, "input_tokens", None), getattr(response, "output_tokens", None),
                getattr(response, "reasoning_tokens", None), getattr(response, "request_id", None),
                error_code, run_id,
            ),
        )


def _mark_agent_error(run_id: str, error: Exception) -> None:
    code = error.code if isinstance(error, (AIServiceError, AgentOutputError)) else "agent_error"
    _run_finish(run_id, error_code=code)
    _trace(run_id, "agent_failed", None, status=code)


def _agent_runs(db: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    runs = _table_rows(
        db,
        """SELECT run_id, agent_name, operation, model, reasoning_effort, input_count,
                  started_at, completed_at, latency_ms, outcome, input_tokens, output_tokens,
                  reasoning_tokens, request_id, error_code
           FROM mediation_agent_runs WHERE case_id = ? ORDER BY started_at, rowid""",
        (case_id,),
    )
    for run in runs:
        run["traces"] = _table_rows(
            db,
            "SELECT event, tool_name, safe_detail_json, created_at FROM mediation_agent_traces WHERE run_id = ? ORDER BY sequence",
            (run["run_id"],),
        )
        for trace in run["traces"]:
            trace["detail"] = json.loads(trace.pop("safe_detail_json"))
        del run["run_id"]
    return runs


def _approval_view(db: sqlite3.Connection, agreement_id: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = {
        row["member_id"]: row
        for row in _table_rows(db, "SELECT member_id, decision, note, created_at FROM mediation_agreement_decisions WHERE agreement_id = ?", (agreement_id,))
    }
    return [
        {
            "member_id": person["member_id"],
            "member_name": person["name"],
            "decision": decisions.get(person["member_id"], {}).get("decision", "pending"),
            "note": decisions.get(person["member_id"], {}).get("note", ""),
        }
        for person in participants
    ]


def _agreement_views(db: sqlite3.Connection, case: dict[str, Any], participants: list[dict[str, Any]], active_member_id: str) -> list[dict[str, Any]]:
    rows = _table_rows(db, "SELECT * FROM mediation_agreements WHERE case_id = ? ORDER BY version DESC", (case["id"],))
    views = []
    by_id = {person["member_id"]: person for person in participants}
    for row in rows:
        tasks = json.loads(row.pop("responsibilities_json"))
        mapped_tasks = []
        for task in tasks:
            target = task.get("participant_id")
            person = by_id.get(target)
            mapped_tasks.append({
                **task,
                "member_id": target if person else None,
                "member_name": "Everyone involved" if target == "all" else (
                    "You" if target == active_member_id else "A roommate"
                    if case["identity_hidden"] and target == case["created_by"] else person["name"] if person else "A roommate"
                ),
            })
        row["responsibilities"] = mapped_tasks
        row["decisions"] = _approval_view(db, row["id"], participants)
        for decision in row["decisions"]:
            if case["identity_hidden"] and decision["member_id"] == case["created_by"] and active_member_id != case["created_by"]:
                decision["member_name"] = "A roommate"
            elif decision["member_id"] == active_member_id:
                decision["member_name"] = "You"
        row["approved_count"] = sum(item["decision"] == "approved" for item in row["decisions"])
        row["required_approvals"] = len(participants)
        views.append(row)
    return views


def _case_view(db: sqlite3.Connection, household_id: str, case_id: str, active_member_id: str) -> dict[str, Any]:
    case_row = db.execute("SELECT * FROM mediation_cases WHERE id = ? AND household_id = ?", (case_id, household_id)).fetchone()
    if case_row is None:
        raise HTTPException(status_code=404, detail="Mediation case not found")
    case = dict(case_row)
    participants = _participant_rows(db, case_id)
    participant_ids = {item["member_id"] for item in participants}
    if active_member_id not in participant_ids:
        raise HTTPException(status_code=403, detail="This case is available only to the roommates involved")
    statements = _table_rows(db, "SELECT member_id, created_at FROM mediation_statements WHERE case_id = ?", (case_id,))
    submitted = {item["member_id"] for item in statements}
    visible_people = []
    for person in participants:
        hidden_creator = case["identity_hidden"] and person["member_id"] == case["created_by"] and active_member_id != case["created_by"]
        visible_people.append({
            "member_id": person["member_id"],
            "name": "A roommate" if hidden_creator else "You" if person["member_id"] == active_member_id else person["name"],
            "color": person["color"],
            "submitted": person["member_id"] in submitted,
        })
    own_statement = db.execute("SELECT body, created_at FROM mediation_statements WHERE case_id = ? AND member_id = ?", (case_id, active_member_id)).fetchone()
    question_rows = _table_rows(db, "SELECT id, question, ordinal, created_at FROM mediation_questions WHERE case_id = ? AND active = 1 ORDER BY ordinal", (case_id,))
    questions = []
    for question in question_rows:
        responses = _table_rows(db, "SELECT member_id FROM mediation_clarification_responses WHERE question_id = ?", (question["id"],))
        own_response = db.execute("SELECT answer, marked_unknown FROM mediation_clarification_responses WHERE question_id = ? AND member_id = ?", (question["id"], active_member_id)).fetchone()
        questions.append({
            "id": question["id"],
            "question": question["question"],
            "response_count": len(responses),
            "required_responses": len(participants),
            "my_answer": own_response["answer"] if own_response else "",
            "my_marked_unknown": bool(own_response["marked_unknown"]) if own_response else False,
            "my_responded": own_response is not None,
        })
    try:
        listening = json.loads(case["listening_json"])
    except (json.JSONDecodeError, TypeError):
        listening = {}
    try:
        mediation = json.loads(case["mediation_json"])
    except (json.JSONDecodeError, TypeError):
        mediation = {}
    agreements = _agreement_views(db, case, participants, active_member_id)
    return {
        "id": case["id"],
        "category": case["category"],
        "status": case["status"],
        "created_at": case["created_at"],
        "updated_at": case["updated_at"],
        "created_by_me": case["created_by"] == active_member_id,
        "identity_hidden": bool(case["identity_hidden"]),
        "participants": visible_people,
        "my_statement": own_statement["body"] if own_statement else "",
        "my_statement_at": own_statement["created_at"] if own_statement else None,
        "all_perspectives_submitted": len(submitted) == len(participants),
        "statement_count": len(submitted),
        "participant_count": len(participants),
        "listening_summary": case["listening_summary"],
        "listening": listening,
        "questions": questions,
        "safety_guidance": case["safety_guidance"],
        "mediation": mediation if case["status"] in ("mediated", "preparing_agreement", "agreement_pending", "revision_required", "active") else {},
        "agreements": agreements,
        "agent_runs": _agent_runs(db, case_id),
    }


def _household_member_ids(db: sqlite3.Connection, household_id: str) -> list[dict[str, Any]]:
    return _table_rows(db, "SELECT id, name, color FROM members WHERE household_id = ? ORDER BY rowid", (household_id,))


def _select_relevant_rules(rules: list[dict[str, Any]], category: str, perspectives: list[dict[str, str]]) -> list[dict[str, Any]]:
    words = set(re.findall(r"[a-z]{3,}", category.lower()))
    for perspective in perspectives:
        words.update(word for word in re.findall(r"[a-z]{3,}", perspective["perspective"].lower()) if word not in _STOP_WORDS)
    ranked = sorted(
        rules,
        key=lambda rule: len(words & set(re.findall(r"[a-z]{3,}", f"{rule['title']} {rule['detail']} {rule['category']}".lower()))),
        reverse=True,
    )
    return [{**rule, "title": rule["title"][:100], "detail": rule["detail"][:360], "category": rule["category"][:60]} for rule in ranked[:4]]


def _listening_payload(people: list[dict[str, Any]], perspectives: list[dict[str, str]]) -> list[dict[str, str]]:
    by_alias = {f"p{person['ordinal'] + 1}": person for person in people}
    return [
        {
            "participant": f"Roommate {item['participant_id'][1:]}",
            "statement": item["perspective"],
        }
        for item in perspectives if item["participant_id"] in by_alias
    ]


def _anonymize_perspectives(case: dict[str, Any], people: list[dict[str, Any]], perspectives: list[dict[str, str]]) -> list[dict[str, str]]:
    masked = [dict(item) for item in perspectives]
    if case["identity_hidden"]:
        private_names = [person["name"] for person in people if person["name"].strip()]
        for item in masked:
            for name in sorted(private_names, key=len, reverse=True):
                item["perspective"] = re.sub(re.escape(name), "a roommate", item["perspective"], flags=re.IGNORECASE)
    return masked


def _anonymize_text(case: dict[str, Any], people: list[dict[str, Any]], value: Any) -> Any:
    if isinstance(value, str):
        if case["identity_hidden"]:
            for person in sorted(people, key=lambda item: len(item["name"]), reverse=True):
                if person["name"].strip():
                    value = re.sub(re.escape(person["name"]), "a roommate", value, flags=re.IGNORECASE)
        return value
    if isinstance(value, list):
        return [_anonymize_text(case, people, item) for item in value]
    if isinstance(value, dict):
        return {key: _anonymize_text(case, people, item) for key, item in value.items()}
    return value


def _save_listening(case_id: str, run_id: str, output: dict[str, Any]) -> None:
    created = now_iso()
    with database() as db:
        db.execute("UPDATE mediation_questions SET active = 0 WHERE case_id = ? AND active = 1", (case_id,))
        for index, question in enumerate(output["clarification_questions"]):
            db.execute(
                "INSERT INTO mediation_questions (id, case_id, question, ordinal, active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (new_id(), case_id, question, index, created),
            )
        case = db.execute("SELECT COUNT(*) AS submitted FROM mediation_statements WHERE case_id = ?", (case_id,)).fetchone()
        count = case["submitted"]
        required = db.execute("SELECT COUNT(*) FROM mediation_participants WHERE case_id = ?", (case_id,)).fetchone()[0]
        has_questions = bool(output["clarification_questions"])
        status = "gathering" if count < required else "clarifications" if has_questions else "ready"
        db.execute(
            "UPDATE mediation_cases SET listening_summary = ?, listening_json = ?, status = ?, updated_at = ? WHERE id = ?",
            (output["neutral_summary"], json.dumps(output), status, created, case_id),
        )
    _trace(run_id, "organized_perspectives", "create_neutral_summary", input_count=count, output_count=1, question_count=len(output["clarification_questions"]))


def _execute_listening(case_id: str, *, refresh: bool) -> None:
    with database() as db:
        case_row = db.execute("SELECT * FROM mediation_cases WHERE id = ?", (case_id,)).fetchone()
        case = dict(case_row)
        people = _participant_rows(db, case_id)
        perspectives = _perspectives(db, case)
    perspectives = _anonymize_perspectives(case, people, perspectives)
    run_id = _run_start(case_id, LISTENING_AGENT, "refresh_summary" if refresh else "initial_listening", "medium", len(perspectives))
    _trace(run_id, "read_submitted_statements", "load_private_perspectives", input_count=len(perspectives), participant_count=len(people))
    try:
        output = listen(
            run_id=run_id,
            category=case["category"],
            perspectives=_listening_payload(people, perspectives),
            refresh=refresh,
        )
        _save_listening(case_id, run_id, output.output)
        _run_finish(run_id, output=output)
        _trace(run_id, "listening_complete", None, output_count=1, question_count=len(output.output["clarification_questions"]), status="success")
    except (AIServiceError, AgentOutputError) as error:
        with database() as db:
            db.execute("UPDATE mediation_cases SET status = 'listening_error', updated_at = ? WHERE id = ? AND status NOT IN ('safety_support', 'active')", (now_iso(), case_id))
        _mark_agent_error(run_id, error)


def _needs_safety_support(text: str) -> bool:
    return bool(_SAFETY_PATTERN.search(text))


def _set_safety_support(db: sqlite3.Connection, case_id: str) -> None:
    db.execute(
        "UPDATE mediation_cases SET status = 'safety_support', safety_guidance = ?, updated_at = ? WHERE id = ?",
        (SAFETY_GUIDANCE, now_iso(), case_id),
    )


@router.get("/api/households/{household_id}/mediations")
def list_mediations(household_id: str, member_id: str = Query(min_length=1)) -> dict[str, Any]:
    with database() as db:
        _member_for_household(db, household_id, member_id)
        cases = db.execute(
            """SELECT c.id FROM mediation_cases c JOIN mediation_participants p ON p.case_id = c.id
               WHERE c.household_id = ? AND p.member_id = ? ORDER BY c.created_at DESC LIMIT 30""",
            (household_id, member_id),
        ).fetchall()
        return {"cases": [_case_view(db, household_id, row["id"], member_id) for row in cases]}


@router.post("/api/households/{household_id}/mediations")
def create_mediation(household_id: str, payload: MediationCreate) -> dict[str, Any]:
    with database() as db:
        _member_for_household(db, household_id, payload.member_id)
        household = db.execute("SELECT name FROM households WHERE id = ?", (household_id,)).fetchone()
        if household is None:
            raise HTTPException(status_code=404, detail="Household not found")
        members = _household_member_ids(db, household_id)
        require_household_member(members, payload.member_id)
        valid_ids = {item["id"] for item in members}
        if any(member_id not in valid_ids for member_id in payload.other_member_ids):
            raise HTTPException(status_code=403, detail="Choose roommates in this household")
        participant_ids = [payload.member_id, *payload.other_member_ids]
        existing = db.execute(
            "SELECT id FROM mediation_cases WHERE household_id = ? AND created_by = ? AND idempotency_key = ?",
            (household_id, payload.member_id, payload.idempotency_key),
        ).fetchone()
        if existing:
            return _case_view(db, household_id, existing["id"], payload.member_id)
        case_id, created = new_id(), now_iso()
        unsafe = _needs_safety_support(payload.statement)
        with database() as write_db:
            write_db.execute(
                """INSERT INTO mediation_cases
                   (id, household_id, category, created_by, identity_hidden, status, idempotency_key,
                    safety_guidance, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (case_id, household_id, payload.category, payload.member_id, int(payload.hide_identity),
                 "safety_support" if unsafe else "gathering", payload.idempotency_key,
                 SAFETY_GUIDANCE if unsafe else "", created, created),
            )
            write_db.executemany(
                "INSERT INTO mediation_participants (case_id, member_id, ordinal) VALUES (?, ?, ?)",
                [(case_id, member_id, index) for index, member_id in enumerate(participant_ids)],
            )
            write_db.execute(
                "INSERT INTO mediation_statements (id, case_id, member_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id(), case_id, payload.member_id, payload.statement, created),
            )
    if not unsafe:
        _execute_listening(case_id, refresh=False)
    with database() as db:
        return _case_view(db, household_id, case_id, payload.member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/statements")
def submit_statement(household_id: str, case_id: str, payload: StatementSubmit) -> dict[str, Any]:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        case = _case_access(db, household_id, case_id, payload.member_id)
        if case["status"] in ("safety_support", "active", "agreement_pending", "revision_required", "mediated", "preparing_agreement", "closed"):
            raise HTTPException(status_code=409, detail="This case is not collecting more perspectives")
        existing = db.execute("SELECT 1 FROM mediation_statements WHERE case_id = ? AND member_id = ?", (case_id, payload.member_id)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Your perspective is already saved and cannot be changed")
        existing_characters = db.execute("SELECT COALESCE(SUM(length(body)), 0) FROM mediation_statements WHERE case_id = ?", (case_id,)).fetchone()[0]
        if existing_characters + len(payload.statement) > MAX_CASE_STATEMENT_CHARACTERS:
            raise HTTPException(status_code=413, detail="Keep the combined roommate statements under 8,000 characters so Homi can consider everyone's perspective together")
        unsafe = _needs_safety_support(payload.statement)
        db.execute(
            "INSERT INTO mediation_statements (id, case_id, member_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id(), case_id, payload.member_id, payload.statement, now_iso()),
        )
        if unsafe:
            _set_safety_support(db, case_id)
        else:
            remaining = db.execute(
                "SELECT COUNT(*) FROM mediation_participants p LEFT JOIN mediation_statements s ON s.case_id = p.case_id AND s.member_id = p.member_id WHERE p.case_id = ? AND s.id IS NULL",
                (case_id,),
            ).fetchone()[0]
    if not unsafe and remaining == 0:
        _execute_listening(case_id, refresh=True)
    with database() as db:
        return _case_view(db, household_id, case_id, payload.member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/clarifications/{question_id}")
def respond_to_clarification(household_id: str, case_id: str, question_id: str, payload: ClarificationSubmit) -> dict[str, Any]:
    with database() as db:
        case = _case_access(db, household_id, case_id, payload.member_id)
        if case["status"] != "clarifications":
            raise HTTPException(status_code=409, detail="This case is not waiting for clarification responses")
        question = db.execute("SELECT id FROM mediation_questions WHERE id = ? AND case_id = ? AND active = 1", (question_id, case_id)).fetchone()
        if question is None:
            raise HTTPException(status_code=404, detail="Clarification question not found")
        prior = db.execute("SELECT 1 FROM mediation_clarification_responses WHERE question_id = ? AND member_id = ?", (question_id, payload.member_id)).fetchone()
        if prior:
            raise HTTPException(status_code=409, detail="Your response is already saved")
        db.execute(
            """INSERT INTO mediation_clarification_responses
               (question_id, member_id, answer, marked_unknown, created_at) VALUES (?, ?, ?, ?, ?)""",
            (question_id, payload.member_id, payload.answer, int(payload.mark_unknown), now_iso()),
        )
        missing = db.execute(
            """SELECT COUNT(*) FROM mediation_questions q CROSS JOIN mediation_participants p
               LEFT JOIN mediation_clarification_responses r ON r.question_id = q.id AND r.member_id = p.member_id
               WHERE q.case_id = ? AND q.active = 1 AND r.member_id IS NULL""",
            (case_id,),
        ).fetchone()[0]
        if missing == 0:
            db.execute("UPDATE mediation_cases SET status = 'ready', updated_at = ? WHERE id = ?", (now_iso(), case_id))
    with database() as db:
        return _case_view(db, household_id, case_id, payload.member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/listen")
def retry_listening(household_id: str, case_id: str, payload: MemberAction) -> dict[str, Any]:
    with database() as db:
        case = _case_access(db, household_id, case_id, payload.member_id)
        if case["status"] != "listening_error":
            raise HTTPException(status_code=409, detail="Listening does not need a retry")
        db.execute("UPDATE mediation_cases SET status = 'gathering', updated_at = ? WHERE id = ?", (now_iso(), case_id))
    _execute_listening(case_id, refresh=True)
    with database() as db:
        return _case_view(db, household_id, case_id, payload.member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/mediate")
def create_mediation_analysis(household_id: str, case_id: str, payload: MemberAction) -> dict[str, Any]:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        case = _case_access(db, household_id, case_id, payload.member_id)
        if case["status"] == "mediated" or case["status"] in ("agreement_pending", "revision_required", "active"):
            return _case_view(db, household_id, case_id, payload.member_id)
        if case["status"] != "ready":
            raise HTTPException(status_code=409, detail="Collect every perspective and complete or mark unknown each clarification before mediation")
        missing_statements = db.execute(
            "SELECT COUNT(*) FROM mediation_participants p LEFT JOIN mediation_statements s ON s.case_id = p.case_id AND s.member_id = p.member_id WHERE p.case_id = ? AND s.id IS NULL",
            (case_id,),
        ).fetchone()[0]
        missing_answers = db.execute(
            """SELECT COUNT(*) FROM mediation_questions q CROSS JOIN mediation_participants p
               LEFT JOIN mediation_clarification_responses r ON r.question_id = q.id AND r.member_id = p.member_id
               WHERE q.case_id = ? AND q.active = 1 AND r.member_id IS NULL""",
            (case_id,),
        ).fetchone()[0]
        if missing_statements or missing_answers:
            raise HTTPException(status_code=409, detail="The case is missing a roommate perspective or clarification response")
        changed = db.execute("UPDATE mediation_cases SET status = 'mediating', updated_at = ? WHERE id = ? AND status = 'ready'", (now_iso(), case_id)).rowcount
        if changed != 1:
            raise HTTPException(status_code=409, detail="Mediation is already being prepared")
        case = dict(db.execute("SELECT * FROM mediation_cases WHERE id = ?", (case_id,)).fetchone())
        people = _participant_rows(db, case_id)
        perspectives = _perspectives(db, case)
        response_rows = _table_rows(
            db,
            """SELECT q.question, r.answer, r.marked_unknown, p.ordinal
               FROM mediation_questions q JOIN mediation_clarification_responses r ON r.question_id = q.id
               JOIN mediation_participants p ON p.case_id = q.case_id AND p.member_id = r.member_id
               WHERE q.case_id = ? AND q.active = 1 ORDER BY q.ordinal, p.ordinal""",
            (case_id,),
        )
        available_rules = _table_rows(db, "SELECT id, title, detail, category FROM house_rules WHERE household_id = ? AND approved = 1 ORDER BY rowid LIMIT 80", (household_id,))
        rules = _select_relevant_rules(available_rules, case["category"], [item for item in perspectives])
        agreements = _table_rows(
            db,
            """SELECT a.title, a.summary, a.responsibilities_json, a.follow_up, c.category
               FROM mediation_agreements a JOIN mediation_cases c ON c.id = a.case_id
               WHERE c.household_id = ? AND c.category = ? AND a.status = 'active' ORDER BY a.updated_at DESC LIMIT 2""",
            (household_id, case["category"]),
        )
        for agreement in agreements:
            agreement["responsibilities"] = json.loads(agreement.pop("responsibilities_json"))
        listening = json.loads(case["listening_json"] or "{}")
        perspectives = _anonymize_perspectives(case, people, perspectives)
        listening = _anonymize_text(case, people, listening)
    run_id = _run_start(case_id, MEDIATION_AGENT, "compare_perspectives_and_rules", "high", len(perspectives))
    _trace(run_id, "read_all_submitted_perspectives", "load_case_perspectives", input_count=len(perspectives), participant_count=len(people))
    _trace(run_id, "retrieve_approved_house_rules", "load_active_house_rules", rule_count=len(rules))
    _trace(run_id, "retrieve_relevant_active_agreements", "load_active_household_agreements", agreement_count=len(agreements))
    clarifications = [
        {"question": row["question"], "response": "Unknown" if row["marked_unknown"] else row["answer"], "participant": f"Roommate {row['ordinal'] + 1}"}
        for row in response_rows
    ]
    try:
        result = mediate(
            run_id=run_id,
            category=case["category"],
            perspectives=_listening_payload(people, perspectives),
            listening=listening,
            clarifications=clarifications,
            active_rules=rules,
            active_agreements=agreements,
        )
        allowed_rules = {rule["id"] for rule in rules}
        result.output["rule_analysis"] = [item for item in result.output["rule_analysis"] if item["rule_id"] in allowed_rules]
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT status FROM mediation_cases WHERE id = ?", (case_id,)).fetchone()[0] != "mediating":
                raise HTTPException(status_code=409, detail="The case changed while mediation was running")
            db.execute("UPDATE mediation_cases SET mediation_json = ?, status = 'mediated', updated_at = ? WHERE id = ?", (json.dumps(result.output), now_iso(), case_id))
        _run_finish(run_id, output=result)
        _trace(run_id, "balanced_resolution_prepared", "compare_evidence_and_propose_next_step", output_count=1, rule_count=len(result.output["rule_analysis"]), status="success")
    except (AIServiceError, AgentOutputError) as error:
        with database() as db:
            db.execute("UPDATE mediation_cases SET status = 'ready', updated_at = ? WHERE id = ? AND status = 'mediating'", (now_iso(), case_id))
        _mark_agent_error(run_id, error)
        raise HTTPException(status_code=429 if isinstance(error, AIServiceError) and (error.code == "rate_limited" or error.http_status == 429) else 502, detail=str(error)) from None
    except HTTPException:
        _mark_agent_error(run_id, AgentOutputError("case_changed", "case_changed"))
        raise
    except sqlite3.Error:
        with database() as db:
            db.execute("UPDATE mediation_cases SET status = 'ready', updated_at = ? WHERE id = ? AND status = 'mediating'", (now_iso(), case_id))
        _mark_agent_error(run_id, AgentOutputError("persistence_error", "persistence_error"))
        raise HTTPException(status_code=500, detail="Could not save the mediation plan") from None
    with database() as db:
        return _case_view(db, household_id, case_id, payload.member_id)


def _participant_agent_input(people: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"participant_id": f"p{person['ordinal'] + 1}", "name": f"Roommate {person['ordinal'] + 1}"}
        for person in people
    ]


def _generate_agreement(household_id: str, case_id: str, member_id: str) -> dict[str, Any]:
    with database() as db:
        case = _case_access(db, household_id, case_id, member_id)
        if case["status"] == "agreement_pending" and case["current_agreement_id"]:
            return _case_view(db, household_id, case_id, member_id)
        if case["status"] == "active" and case["current_agreement_id"]:
            return _case_view(db, household_id, case_id, member_id)
        if case["status"] not in ("mediated", "revision_required"):
            raise HTTPException(status_code=409, detail="Finish mediation before preparing an agreement")
        people = _participant_rows(db, case_id)
        current = db.execute("SELECT * FROM mediation_agreements WHERE id = ?", (case["current_agreement_id"],)).fetchone() if case["current_agreement_id"] else None
        if current and case["status"] == "revision_required":
            requester = db.execute("SELECT 1 FROM mediation_agreement_decisions WHERE agreement_id = ? AND member_id = ? AND decision IN ('rejected', 'changes_requested')", (current["id"], member_id)).fetchone()
            if not requester:
                raise HTTPException(status_code=403, detail="A roommate who rejected or requested a change must start the revision")
        revisions = []
        if current:
            revisions = _table_rows(db, "SELECT note FROM mediation_agreement_decisions WHERE agreement_id = ? AND decision IN ('rejected', 'changes_requested') AND note != ''", (current["id"],))
        mediation = _anonymize_text(case, people, json.loads(case["mediation_json"] or "{}"))
        change_requests = _anonymize_text(case, people, [item["note"] for item in revisions])
        previous = None
        if current:
            previous = {
                "title": current["title"],
                "summary": current["summary"],
                "responsibilities": json.loads(current["responsibilities_json"]),
                "follow_up": current["follow_up"],
            }
            previous = _anonymize_text(case, people, previous)
    run_id = _run_start(case_id, AGREEMENT_AGENT, "prepare_pending_agreement" if not current else "revise_pending_agreement", "medium", len(people))
    reservation_conflict = False
    with database() as write_db:
        write_db.execute("BEGIN IMMEDIATE")
        current_status = write_db.execute("SELECT status FROM mediation_cases WHERE id = ?", (case_id,)).fetchone()[0]
        if current_status != case["status"]:
            reservation_conflict = True
        else:
            write_db.execute("UPDATE mediation_cases SET status = 'preparing_agreement', updated_at = ? WHERE id = ?", (now_iso(), case_id))
    if reservation_conflict:
        _run_finish(run_id, error_code="case_changed")
        raise HTTPException(status_code=409, detail="Another roommate is already preparing this agreement")
    _trace(run_id, "structure_roommate_responsibilities", "map_actions_to_case_participants", participant_count=len(people), input_count=1)
    try:
        result = draft_agreement(
            run_id=run_id,
            resolution=mediation,
            participants=_participant_agent_input(people),
            previous=previous,
            change_requests=change_requests,
        )
        by_alias = {f"p{person['ordinal'] + 1}": person["member_id"] for person in people}
        responsibilities = [
            {**item, "participant_id": by_alias.get(item["participant_id"], item["participant_id"])}
            for item in result.output["responsibilities"]
        ]
        now = now_iso()
        agreement_id = new_id()
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            current_case = db.execute("SELECT status, current_agreement_id FROM mediation_cases WHERE id = ?", (case_id,)).fetchone()
            if current_case["status"] != "preparing_agreement" or current_case["current_agreement_id"] != case["current_agreement_id"]:
                raise HTTPException(status_code=409, detail="The case changed while the agreement was being prepared")
            version = db.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM mediation_agreements WHERE case_id = ?", (case_id,)).fetchone()[0]
            if current:
                db.execute("UPDATE mediation_agreements SET status = 'superseded', updated_at = ? WHERE id = ?", (now, current["id"]))
            db.execute(
                """INSERT INTO mediation_agreements
                   (id, case_id, version, run_id, title, summary, responsibilities_json, follow_up, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (agreement_id, case_id, version, run_id, result.output["title"], result.output["summary"], json.dumps(responsibilities), result.output["follow_up"], now, now),
            )
            db.execute("UPDATE mediation_cases SET current_agreement_id = ?, status = 'agreement_pending', updated_at = ? WHERE id = ?", (agreement_id, now, case_id))
        _run_finish(run_id, output=result)
        _trace(run_id, "pending_agreement_created", "create_pending_agreement", output_count=1, participant_count=len(people), status="pending")
    except (AIServiceError, AgentOutputError) as error:
        with database() as db:
            db.execute("UPDATE mediation_cases SET status = ?, updated_at = ? WHERE id = ? AND status = 'preparing_agreement'", ("revision_required" if current else "mediated", now_iso(), case_id))
        _mark_agent_error(run_id, error)
        raise HTTPException(status_code=429 if isinstance(error, AIServiceError) and (error.code == "rate_limited" or error.http_status == 429) else 502, detail=str(error)) from None
    except HTTPException:
        with database() as db:
            db.execute("UPDATE mediation_cases SET status = ?, updated_at = ? WHERE id = ? AND status = 'preparing_agreement'", ("revision_required" if current else "mediated", now_iso(), case_id))
        _mark_agent_error(run_id, AgentOutputError("case_changed", "case_changed"))
        raise
    except sqlite3.Error:
        with database() as db:
            db.execute("UPDATE mediation_cases SET status = ?, updated_at = ? WHERE id = ? AND status = 'preparing_agreement'", ("revision_required" if current else "mediated", now_iso(), case_id))
        _mark_agent_error(run_id, AgentOutputError("persistence_error", "persistence_error"))
        raise HTTPException(status_code=500, detail="Could not save the pending agreement") from None
    with database() as db:
        return _case_view(db, household_id, case_id, member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/agreements")
def create_agreement(household_id: str, case_id: str, payload: MemberAction) -> dict[str, Any]:
    return _generate_agreement(household_id, case_id, payload.member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/agreements/{agreement_id}/decision")
def decide_agreement(household_id: str, case_id: str, agreement_id: str, payload: AgreementDecision) -> dict[str, Any]:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        case = _case_access(db, household_id, case_id, payload.member_id)
        if case["current_agreement_id"] != agreement_id or case["status"] != "agreement_pending":
            raise HTTPException(status_code=409, detail="This agreement is not awaiting approvals")
        agreement = db.execute("SELECT status FROM mediation_agreements WHERE id = ? AND case_id = ?", (agreement_id, case_id)).fetchone()
        if agreement is None or agreement["status"] != "pending":
            raise HTTPException(status_code=409, detail="This agreement is no longer pending")
        if db.execute("SELECT 1 FROM mediation_agreement_decisions WHERE agreement_id = ? AND member_id = ?", (agreement_id, payload.member_id)).fetchone():
            raise HTTPException(status_code=409, detail="Your response is already saved and cannot be repeated")
        translated = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[payload.decision]
        db.execute(
            "INSERT INTO mediation_agreement_decisions (agreement_id, member_id, decision, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (agreement_id, payload.member_id, translated, payload.note, now_iso()),
        )
        if translated != "approved":
            db.execute("UPDATE mediation_agreements SET status = 'revision_required', updated_at = ? WHERE id = ?", (now_iso(), agreement_id))
            db.execute("UPDATE mediation_cases SET status = 'revision_required', updated_at = ? WHERE id = ?", (now_iso(), case_id))
        else:
            total = db.execute("SELECT COUNT(*) FROM mediation_participants WHERE case_id = ?", (case_id,)).fetchone()[0]
            decisions = db.execute("SELECT COUNT(*) AS total, SUM(decision = 'approved') AS approved FROM mediation_agreement_decisions WHERE agreement_id = ?", (agreement_id,)).fetchone()
            if decisions["total"] == total and decisions["approved"] == total:
                valid = db.execute(
                    """SELECT COUNT(*) FROM mediation_participants p JOIN mediation_agreement_decisions d
                       ON d.member_id = p.member_id WHERE p.case_id = ? AND d.agreement_id = ? AND d.decision = 'approved'""",
                    (case_id, agreement_id),
                ).fetchone()[0]
                if valid == total:
                    db.execute("UPDATE mediation_agreements SET status = 'active', updated_at = ? WHERE id = ? AND status = 'pending'", (now_iso(), agreement_id))
                    db.execute("UPDATE mediation_cases SET status = 'active', updated_at = ? WHERE id = ? AND current_agreement_id = ?", (now_iso(), case_id, agreement_id))
    with database() as db:
        return _case_view(db, household_id, case_id, payload.member_id)


@router.post("/api/households/{household_id}/mediations/{case_id}/agreements/{agreement_id}/revise")
def revise_agreement(household_id: str, case_id: str, agreement_id: str, payload: MemberAction) -> dict[str, Any]:
    with database() as db:
        case = _case_access(db, household_id, case_id, payload.member_id)
        if case["current_agreement_id"] != agreement_id or case["status"] != "revision_required":
            raise HTTPException(status_code=409, detail="This agreement has no open rejection or change request")
    return _generate_agreement(household_id, case_id, payload.member_id)
