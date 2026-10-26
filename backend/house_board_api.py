from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.ai_service import AIServiceError, finish_agent_run, start_agent_run
from backend.house_board_agent import (
    AGENT_NAME,
    AGENT_VERSION,
    REASONING_EFFORT,
    OUTPUT_TOKEN_BUDGET,
    RETRY_OUTPUT_TOKEN_BUDGET,
    BoardAgentOutputError,
    analyze_post,
)


def _main_module():
    """Resolve shared app helpers lazily to keep the router import cycle-free."""
    from backend import main

    return main


def database():
    return _main_module().database()


def household_payload(*args, **kwargs):
    return _main_module().household_payload(*args, **kwargs)


def new_id():
    return _main_module().new_id()


def now_iso():
    return _main_module().now_iso()


def require_household_member(*args, **kwargs):
    return _main_module().require_household_member(*args, **kwargs)


router = APIRouter()
_CLASSIFICATION_LABELS = {
    "announcement": "Announcement",
    "request": "Request",
    "reminder": "Reminder",
    "question": "Question",
}
_EXPLICIT_PERMISSION_REQUEST = re.compile(
    r"\b(?:can|could|may|would)\s+(?:i|we)\b"
    r"|\b(?:is|would)\s+it\s+(?:okay|ok|alright)\s+(?:if|for)\b"
    r"|\bdo\s+you\s+mind\s+if\b",
    re.IGNORECASE,
)


def _contains_explicit_permission_request(text: str) -> bool:
    """Keep clear consent requests approval-gated even if the model misclassifies them."""
    return bool(_EXPLICIT_PERMISSION_REQUEST.search(" ".join(text.split())))


class BoardDecision(BaseModel):
    member_id: str
    version: int = Field(ge=1)
    decision: Literal["approve", "reject", "request_changes"]
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return " ".join(value.split())


class BoardRevision(BaseModel):
    member_id: str
    message: str = Field(min_length=2, max_length=2_000)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=100)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Share a little more so the post is clear")
        return value


class BoardClarification(BaseModel):
    member_id: str
    version: int = Field(ge=1)
    answer: str = Field(min_length=2, max_length=600)

    @field_validator("answer")
    @classmethod
    def clean_answer(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Add a short clarification")
        return value


class NotificationRead(BaseModel):
    member_id: str


def _record_trace(run_id: str, announcement_id: str, version: int, sequence: int, event: str, tool_name: str, detail: dict[str, Any] | None = None) -> None:
    with database() as db:
        db.execute(
            """INSERT INTO house_board_agent_traces
               (run_id, announcement_id, version, sequence, event, tool_name, safe_detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, announcement_id, version, sequence, event, tool_name,
             json.dumps(detail or {}, ensure_ascii=True, sort_keys=True), now_iso()),
        )


def _members_and_rules(db, household_id: str) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    household = db.execute("SELECT id, name FROM households WHERE id = ?", (household_id,)).fetchone()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    members = [dict(row) for row in db.execute(
        "SELECT id, name FROM members WHERE household_id = ? ORDER BY rowid",
        (household_id,),
    )]
    rules = [dict(row) for row in db.execute(
        """SELECT id, title, detail FROM house_rules
           WHERE household_id = ? AND approved = 1 ORDER BY rowid LIMIT 50""",
        (household_id,),
    )]
    return dict(household), members, rules


def _insert_notification(db, *, household_id: str, recipient_id: str, title: str, detail: str, kind: str, announcement_id: str, version: int, event: str, created: str) -> None:
    if not recipient_id:
        return
    dedupe_key = f"board:{announcement_id}:v{version}:{event}:{recipient_id}"
    db.execute(
        """INSERT OR IGNORE INTO notifications
           (id, household_id, title, detail, kind, created_at, is_read, recipient_id,
            entity_type, entity_id, dedupe_key)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'board_post', ?, ?)""",
        (new_id(), household_id, title[:120], detail[:240], kind, created,
         recipient_id, announcement_id, dedupe_key),
    )


def _create_post_notices(db, *, household_id: str, post_id: str, version: int, author_id: str, author_name: str, members: list[dict[str, str]], analysis: dict[str, Any], approval_status: str, ai_status: str, created: str, event_prefix: str = "new_post") -> None:
    summary = analysis.get("summary") or "A new note was shared on the House Board."
    conflicts = analysis.get("rule_conflicts") or []
    if ai_status != "complete":
        for member in members:
            if member["id"] != author_id:
                _insert_notification(
                    db, household_id=household_id, recipient_id=member["id"],
                    title=f"A House Board note from {author_name}",
                    detail="Little Homi's check is unavailable. Read the note as written; no permission was assessed.",
                    kind="board", announcement_id=post_id, version=version,
                    event=f"{event_prefix}:ai_unavailable", created=created,
                )
        return

    if approval_status == "clarification_needed":
        _insert_notification(
            db, household_id=household_id, recipient_id=author_id,
            title="Little Homi needs one more detail",
            detail=analysis.get("clarification_question") or "Please clarify one detail on your Board post.",
            kind="board", announcement_id=post_id, version=version,
            event=f"{event_prefix}:clarification", created=created,
        )
    elif approval_status == "pending":
        for member in members:
            if member["id"] != author_id:
                _insert_notification(
                    db, household_id=household_id, recipient_id=member["id"],
                    title=f"{author_name} needs a roommate decision",
                    detail=summary,
                    kind="board", announcement_id=post_id, version=version,
                    event=f"{event_prefix}:approval_request", created=created,
                )
        if conflicts:
            _insert_notification(
                db, household_id=household_id, recipient_id=author_id,
                title="A possible House Rules overlap",
                detail=conflicts[0]["explanation"], kind="board",
                announcement_id=post_id, version=version,
                event=f"{event_prefix}:rule_conflict", created=created,
            )
    else:
        for member in members:
            if member["id"] != author_id:
                _insert_notification(
                    db, household_id=household_id, recipient_id=member["id"],
                    title=f"A new House Board {analysis.get('classification', 'announcement')}",
                    detail=summary,
                    kind="board", announcement_id=post_id, version=version,
                    event=f"{event_prefix}:post", created=created,
                )


def _run_analysis(*, household_id: str, post_id: str, version: int, author_id: str, message: str, clarification: str, run_id: str, operation: str) -> dict[str, Any]:
    with database() as db:
        household, members, rules = _members_and_rules(db, household_id)
    require_household_member(members, author_id)
    _record_trace(run_id, post_id, version, 1, "loaded_household_members", "retrieve_relevant_household_members", {"member_count": len(members)})
    _record_trace(run_id, post_id, version, 2, "loaded_active_approved_rules", "retrieve_active_house_rules", {"rule_count": len(rules)})
    _record_trace(run_id, post_id, version, 3, "analysis_started", "analyze_submitted_post", {"message_characters": len(message), "has_clarification": bool(clarification)})

    start_agent_run(
        run_id=run_id,
        household_id=household_id,
        agent_name=AGENT_NAME,
        agent_version=AGENT_VERSION,
        operation=operation,
        reasoning_effort=REASONING_EFFORT,
        participant_count=len(members),
        preference_count=len(rules),
        category_summary=["house_board_post"],
    )
    started = time.perf_counter()
    try:
        result, analysis = analyze_post(
            run_id=run_id,
            message=message,
            clarification=clarification,
            household_name=household["name"],
            members=members,
            active_rules=rules,
            on_output_limit_retry=lambda: _record_trace(
                run_id, post_id, version, 4, "output_limit_retry",
                "retry_incomplete_structured_analysis",
                {
                    "first_output_token_budget": OUTPUT_TOKEN_BUDGET,
                    "retry_output_token_budget": RETRY_OUTPUT_TOKEN_BUDGET,
                },
            ),
        )
    except (AIServiceError, BoardAgentOutputError) as error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=getattr(error, "code", "smart_board_error"),
        )
        _record_trace(run_id, post_id, version, 5, "analysis_unavailable", "handle_ai_failure_without_fabricating_content", {"error_code": getattr(error, "code", "smart_board_error")})
        return {"ok": False, "error_code": getattr(error, "code", "smart_board_error")}
    except Exception:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code="smart_board_internal_error",
        )
        _record_trace(run_id, post_id, version, 5, "analysis_unavailable", "handle_ai_failure_without_fabricating_content", {"error_code": "smart_board_internal_error"})
        return {"ok": False, "error_code": "smart_board_internal_error"}

    finish_agent_run(
        run_id=run_id,
        outcome="success",
        latency_ms=int((time.perf_counter() - started) * 1000),
        proposal_count=1,
        result=result,
    )
    _record_trace(run_id, post_id, version, 5, "analysis_validated", "validate_structured_output_and_rule_references", {"rule_conflict_count": len(analysis["rule_conflicts"])})
    return {"ok": True, "analysis": analysis, "response_model": result.model}


def _save_analysis(*, household_id: str, post_id: str, version: int, author_id: str, analysis_result: dict[str, Any]) -> str:
    created = now_iso()
    with database() as db:
        post = db.execute(
            "SELECT * FROM announcements WHERE id = ? AND household_id = ?",
            (post_id, household_id),
        ).fetchone()
        if post is None or int(post["version"]) != version:
            raise HTTPException(status_code=409, detail="This Board post changed while Little Homi was reviewing it")
        household, members, _ = _members_and_rules(db, household_id)
        author = next((member for member in members if member["id"] == author_id), None)
        if author is None:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")

        if not analysis_result.get("ok"):
            analysis = {}
            category = "Announcement"
            ai_status = "unavailable"
            requires_approval = False
            approval_status = "not_assessed"
            body = post["original_body"]
            post_status = "ai_unavailable"
        else:
            analysis = analysis_result["analysis"]
            category = _CLASSIFICATION_LABELS[analysis["classification"]]
            ai_status = "complete"
            requires_approval = bool(
                analysis["approval_required"]
                or analysis["classification"] == "request"
                or analysis["rule_conflicts"]
                or _contains_explicit_permission_request(
                    f"{post['original_body']} {post['clarification_text']}"
                )
            )
            if analysis["clarification_question"]:
                approval_status = "clarification_needed"
                post_status = "clarification_needed"
            elif requires_approval:
                approval_status = "pending" if len(members) > 1 else "no_other_roommates"
                post_status = "approval_pending" if len(members) > 1 else "approval_unavailable"
            elif analysis["response_required"]:
                approval_status = "response_requested"
                post_status = "published"
            else:
                approval_status = "not_required"
                post_status = "published"
            body = analysis["summary"]

        db.execute(
            """UPDATE announcements SET body = ?, category = ?, post_type = ?, ai_status = ?,
               analysis_json = ?, requires_approval = ?, approval_status = ?
               WHERE id = ? AND household_id = ? AND version = ?""",
            (body, category, analysis.get("classification", "announcement"), ai_status,
             json.dumps(analysis, ensure_ascii=False, separators=(",", ":")),
             int(requires_approval), approval_status, post_id, household_id, version),
        )
        db.execute(
            """UPDATE board_post_versions SET category = ?, body = ?, ai_status = ?, analysis_json = ?,
               requires_approval = ?, approval_status = ?
               WHERE announcement_id = ? AND version = ?""",
            (category, body, ai_status, json.dumps(analysis, ensure_ascii=False, separators=(",", ":")),
             int(requires_approval), approval_status, post_id, version),
        )

        db.execute("DELETE FROM announcement_approvals WHERE announcement_id = ? AND version = ?", (post_id, version))
        if approval_status == "pending":
            approvers = [member for member in members if member["id"] != author_id]
            db.executemany(
                """INSERT INTO announcement_approvals
                   (announcement_id, version, member_id, decision, note, updated_at)
                   VALUES (?, ?, ?, 'pending', '', ?)""",
                [(post_id, version, member["id"], created) for member in approvers],
            )
        _create_post_notices(
            db, household_id=household_id, post_id=post_id, version=version,
            author_id=author_id, author_name=author["name"], members=members,
            analysis=analysis, approval_status=approval_status, ai_status=ai_status,
            created=created,
        )
    return post_status


def _board_response(household_id: str, member_id: str, post_id: str) -> dict[str, Any]:
    with database() as db:
        result = household_payload(db, household_id, member_id)
    result["board_post_id"] = post_id
    return result


def _analyze_and_save(*, household_id: str, post_id: str, version: int, author_id: str, message: str, clarification: str = "", operation: str = "analyze_post") -> str:
    run_id = new_id()
    analysis_result = _run_analysis(
        household_id=household_id, post_id=post_id, version=version,
        author_id=author_id, message=message, clarification=clarification,
        run_id=run_id, operation=operation,
    )
    status = _save_analysis(
        household_id=household_id, post_id=post_id, version=version,
        author_id=author_id, analysis_result=analysis_result,
    )
    _record_trace(run_id, post_id, version, 6, "post_and_notifications_saved", "save_board_post_and_relevant_notifications", {"post_status": status})
    return status


def create_board_post(household_id: str, payload) -> dict[str, Any]:
    created = now_iso()
    post_id = new_id()
    with database() as db:
        household, members, _ = _members_and_rules(db, household_id)
        require_household_member(members, payload.author_id)
        duplicate = db.execute(
            """SELECT announcement_id FROM board_post_versions
               WHERE household_id = ? AND author_id = ? AND idempotency_key = ?""",
            (household_id, payload.author_id, payload.idempotency_key),
        ).fetchone()
        if duplicate:
            post_id = duplicate["announcement_id"]
            return _board_response(household_id, payload.author_id, post_id)
        db.execute(
            """INSERT INTO announcements
               (id, household_id, author_id, category, body, created_at, original_body,
                clarification_text, post_type, ai_status, analysis_json, requires_approval,
                approval_status, version, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, '', 'announcement', 'pending', '{}', 0, 'analyzing', 1, ?)""",
            (post_id, household_id, payload.author_id, payload.category, payload.body, created,
             payload.body, payload.idempotency_key),
        )
        db.execute(
            """INSERT INTO board_post_versions
               (announcement_id, version, household_id, author_id, idempotency_key,
                original_body, clarification_text, category, body, ai_status, analysis_json,
                requires_approval, approval_status, created_at)
               VALUES (?, 1, ?, ?, ?, ?, '', ?, ?, 'pending', '{}', 0, 'analyzing', ?)""",
            (post_id, household_id, payload.author_id, payload.idempotency_key,
             payload.body, payload.category, payload.body, created),
        )
    status = _analyze_and_save(
        household_id=household_id, post_id=post_id, version=1,
        author_id=payload.author_id, message=payload.body,
    )
    response = _board_response(household_id, payload.author_id, post_id)
    response["board_post_status"] = status
    return response


@router.get("/api/households/{household_id}/notifications")
def list_notifications(household_id: str, member_id: str) -> dict[str, Any]:
    with database() as db:
        members = [dict(row) for row in db.execute("SELECT id, name FROM members WHERE household_id = ?", (household_id,))]
        require_household_member(members, member_id)
        notifications = [dict(row) for row in db.execute(
            """SELECT * FROM notifications WHERE household_id = ?
               AND (recipient_id IS NULL OR recipient_id = ?)
               ORDER BY created_at DESC, rowid DESC LIMIT 50""",
            (household_id, member_id),
        )]
    for item in notifications:
        item["is_read"] = bool(item["is_read"])
    return {"notifications": notifications}


@router.post("/api/households/{household_id}/notifications/{notification_id}/read")
def mark_notification_read(household_id: str, notification_id: str, payload: NotificationRead) -> dict[str, Any]:
    with database() as db:
        members = [dict(row) for row in db.execute("SELECT id, name FROM members WHERE household_id = ?", (household_id,))]
        require_household_member(members, payload.member_id)
        updated = db.execute(
            """UPDATE notifications SET is_read = 1 WHERE id = ? AND household_id = ?
               AND (recipient_id IS NULL OR recipient_id = ?)""",
            (notification_id, household_id, payload.member_id),
        )
        if updated.rowcount == 0:
            raise HTTPException(status_code=404, detail="Notification not found for this roommate")
    return _board_response(household_id, payload.member_id, "")


@router.post("/api/households/{household_id}/announcements/{announcement_id}/clarify")
def clarify_board_post(household_id: str, announcement_id: str, payload: BoardClarification) -> dict[str, Any]:
    with database() as db:
        members = [dict(row) for row in db.execute("SELECT id, name FROM members WHERE household_id = ?", (household_id,))]
        require_household_member(members, payload.member_id)
        post = db.execute("SELECT * FROM announcements WHERE id = ? AND household_id = ?", (announcement_id, household_id)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="House Board post not found")
        if post["author_id"] != payload.member_id:
            raise HTTPException(status_code=403, detail="Only the roommate who shared this post can answer its clarification")
        if int(post["version"]) != payload.version:
            raise HTTPException(status_code=409, detail="This post has changed. Refresh before clarifying it.")
        if post["approval_status"] != "clarification_needed":
            if post["clarification_text"] == payload.answer:
                return _board_response(household_id, payload.member_id, announcement_id)
            raise HTTPException(status_code=409, detail="This post is not waiting for a clarification")
        if post["clarification_text"]:
            if post["clarification_text"] == payload.answer:
                return _board_response(household_id, payload.member_id, announcement_id)
            raise HTTPException(status_code=409, detail="This clarification was already submitted. Revise the post to add another detail.")
        message = post["original_body"]
        db.execute("UPDATE announcements SET clarification_text = ? WHERE id = ?", (payload.answer, announcement_id))
        db.execute("UPDATE board_post_versions SET clarification_text = ? WHERE announcement_id = ? AND version = ?", (payload.answer, announcement_id, payload.version))
    status = _analyze_and_save(
        household_id=household_id, post_id=announcement_id, version=payload.version,
        author_id=payload.member_id, message=message, clarification=payload.answer,
        operation="clarify_post",
    )
    response = _board_response(household_id, payload.member_id, announcement_id)
    response["board_post_status"] = status
    return response


@router.post("/api/households/{household_id}/announcements/{announcement_id}/decision")
def decide_board_request(household_id: str, announcement_id: str, payload: BoardDecision) -> dict[str, Any]:
    created = now_iso()
    with database() as db:
        members = [dict(row) for row in db.execute("SELECT id, name FROM members WHERE household_id = ? ORDER BY rowid", (household_id,))]
        require_household_member(members, payload.member_id)
        post = db.execute("SELECT * FROM announcements WHERE id = ? AND household_id = ?", (announcement_id, household_id)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="House Board post not found")
        if int(post["version"]) != payload.version:
            raise HTTPException(status_code=409, detail="This request has changed. Refresh before responding.")
        if post["approval_status"] != "pending":
            raise HTTPException(status_code=409, detail="This request is no longer waiting for roommate decisions")
        if payload.member_id == post["author_id"]:
            raise HTTPException(status_code=403, detail="The author cannot approve their own request")
        approval = db.execute(
            """SELECT decision FROM announcement_approvals
               WHERE announcement_id = ? AND version = ? AND member_id = ?""",
            (announcement_id, payload.version, payload.member_id),
        ).fetchone()
        if approval is None:
            raise HTTPException(status_code=403, detail="You are not a required approver for this request")
        if approval["decision"] != "pending":
            raise HTTPException(status_code=409, detail="Your decision for this request was already recorded")
        approver_rows = [dict(row) for row in db.execute(
            """SELECT member_id, decision FROM announcement_approvals
               WHERE announcement_id = ? AND version = ?""",
            (announcement_id, payload.version),
        )]
        expected = {member["id"] for member in members if member["id"] != post["author_id"]}
        actual = {row["member_id"] for row in approver_rows}
        if actual != expected or not expected:
            raise HTTPException(status_code=409, detail="The household approver list changed. Revise the request to start a fresh approval round.")

        decision = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[payload.decision]
        db.execute(
            """UPDATE announcement_approvals SET decision = ?, note = ?, updated_at = ?
               WHERE announcement_id = ? AND version = ? AND member_id = ? AND decision = 'pending'""",
            (decision, payload.note, created, announcement_id, payload.version, payload.member_id),
        )
        if decision == "rejected":
            approval_status = "rejected"
            post_status = "rejected"
        elif decision == "changes_requested":
            approval_status = "changes_requested"
            post_status = "changes_requested"
        else:
            updated_rows = [dict(row) for row in db.execute(
                """SELECT member_id, decision FROM announcement_approvals
                   WHERE announcement_id = ? AND version = ?""",
                (announcement_id, payload.version),
            )]
            approval_status = "approved" if {row["member_id"] for row in updated_rows} == expected and all(row["decision"] == "approved" for row in updated_rows) else "pending"
            post_status = "approved" if approval_status == "approved" else "approval_pending"

        db.execute(
            "UPDATE announcements SET approval_status = ? WHERE id = ? AND household_id = ? AND version = ?",
            (approval_status, announcement_id, household_id, payload.version),
        )
        db.execute(
            "UPDATE board_post_versions SET approval_status = ? WHERE announcement_id = ? AND version = ?",
            (approval_status, announcement_id, payload.version),
        )
        actor = next(member for member in members if member["id"] == payload.member_id)
        author = next(member for member in members if member["id"] == post["author_id"])
        message = {
            "approved": f"{actor['name']} approved your House Board request.",
            "rejected": f"{actor['name']} declined your House Board request.",
            "changes_requested": f"{actor['name']} asked for a change to your House Board request.",
        }[decision]
        _insert_notification(
            db, household_id=household_id, recipient_id=author["id"],
            title="A roommate responded to your request", detail=message,
            kind="board", announcement_id=announcement_id, version=payload.version,
            event=f"decision:{payload.member_id}:{decision}", created=created,
        )
        if approval_status in {"approved", "rejected", "changes_requested"}:
            outcome = {
                "approved": "Everyone approved this request.",
                "rejected": "This request was not approved.",
                "changes_requested": "A roommate requested a change before this can move forward.",
            }[approval_status]
            for member in members:
                if member["id"] != payload.member_id:
                    _insert_notification(
                        db, household_id=household_id, recipient_id=member["id"],
                        title="House Board request update", detail=outcome,
                        kind="board", announcement_id=announcement_id, version=payload.version,
                        event=f"outcome:{approval_status}", created=created,
                    )
    response = _board_response(household_id, payload.member_id, announcement_id)
    response["board_post_status"] = post_status
    return response


@router.post("/api/households/{household_id}/announcements/{announcement_id}/revise")
def revise_board_post(household_id: str, announcement_id: str, payload: BoardRevision) -> dict[str, Any]:
    created = now_iso()
    with database() as db:
        members = [dict(row) for row in db.execute("SELECT id, name FROM members WHERE household_id = ? ORDER BY rowid", (household_id,))]
        require_household_member(members, payload.member_id)
        post = db.execute("SELECT * FROM announcements WHERE id = ? AND household_id = ?", (announcement_id, household_id)).fetchone()
        if post is None:
            raise HTTPException(status_code=404, detail="House Board post not found")
        if post["author_id"] != payload.member_id:
            raise HTTPException(status_code=403, detail="Only the roommate who shared this post can revise it")
        duplicate = db.execute(
            """SELECT version FROM board_post_versions WHERE announcement_id = ? AND author_id = ? AND idempotency_key = ?""",
            (announcement_id, payload.member_id, payload.idempotency_key),
        ).fetchone()
        if duplicate:
            return _board_response(household_id, payload.member_id, announcement_id)
        if not (bool(post["requires_approval"]) or post["approval_status"] in {"clarification_needed", "changes_requested", "rejected", "approved", "not_assessed"}):
            raise HTTPException(status_code=409, detail="Only requests and posts awaiting clarification can be revised")
        version = int(post["version"]) + 1
        db.execute(
            """UPDATE announcements SET original_body = ?, clarification_text = '', body = ?,
               ai_status = 'pending', analysis_json = '{}', requires_approval = 0,
               approval_status = 'analyzing', version = ?, idempotency_key = ?
               WHERE id = ? AND household_id = ?""",
            (payload.message, payload.message, version, payload.idempotency_key, announcement_id, household_id),
        )
        db.execute(
            """INSERT INTO board_post_versions
               (announcement_id, version, household_id, author_id, idempotency_key,
                original_body, clarification_text, category, body, ai_status, analysis_json,
                requires_approval, approval_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, 'pending', '{}', 0, 'analyzing', ?)""",
            (announcement_id, version, household_id, payload.member_id, payload.idempotency_key,
             payload.message, post["category"], payload.message, created),
        )
    status = _analyze_and_save(
        household_id=household_id, post_id=announcement_id, version=version,
        author_id=payload.member_id, message=payload.message, operation="revise_post",
    )
    response = _board_response(household_id, payload.member_id, announcement_id)
    response["board_post_status"] = status
    return response
