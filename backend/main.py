from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterator, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from backend.ai_service import (
    AI_MODEL,
    AIServiceError,
    SUPPORTED_REASONING_EFFORTS,
    finish_agent_run,
    initialize_usage_logs,
    start_agent_run,
)
from backend.house_rules_agent import (
    AGENT_NAME,
    AGENT_VERSION,
    REASONING_EFFORT,
    RULE_CATEGORIES,
    RuleAgentOutputError,
    generate_proposals,
    revise_proposal,
)
from backend.mediation_agents import (
    AGENT_VERSION as MEDIATION_AGENT_VERSION,
    AGREEMENT_AGENT,
    AgentOutputError,
    LISTENING_AGENT,
    MEDIATION_AGENT,
    draft_agreement,
    listen,
    mediate,
)


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")
DATABASE_PATH = Path(os.getenv("HOMI_DATABASE_PATH", str(ROOT / "backend" / "data" / "homi.sqlite")))
DEMO_ID = "willow-house-demo"

app = FastAPI(title="homi. household API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:5175", "http://localhost:5175", "http://127.0.0.1:5186", "http://localhost:5186", "http://127.0.0.1:5187", "http://localhost:5187"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_database() -> None:
    with database() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS households (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS members (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Roommate',
                bio TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT 'sage',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS announcements (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                author_id TEXT REFERENCES members(id) ON DELETE SET NULL,
                category TEXT NOT NULL DEFAULT 'Announcement',
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                original_body TEXT NOT NULL DEFAULT '',
                clarification_text TEXT NOT NULL DEFAULT '',
                post_type TEXT NOT NULL DEFAULT 'announcement',
                ai_status TEXT NOT NULL DEFAULT 'not_analyzed',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                requires_approval INTEGER NOT NULL DEFAULT 0,
                approval_status TEXT NOT NULL DEFAULT 'not_required',
                version INTEGER NOT NULL DEFAULT 1,
                idempotency_key TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS chores (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                assignee_id TEXT REFERENCES members(id) ON DELETE SET NULL,
                due_label TEXT NOT NULL,
                due_date TEXT,
                room TEXT NOT NULL DEFAULT 'Home',
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                amount_cents INTEGER,
                due_label TEXT NOT NULL,
                due_date TEXT,
                split_type TEXT NOT NULL DEFAULT 'equal',
                status TEXT NOT NULL DEFAULT 'Upcoming',
                payer_id TEXT REFERENCES members(id) ON DELETE SET NULL,
                split_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS expense_shares (
                expense_id TEXT NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                paid_at TEXT,
                paid_by_member_id TEXT REFERENCES members(id) ON DELETE SET NULL,
                PRIMARY KEY(expense_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS house_rules (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                category TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rule_preferences (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                preference TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(household_id, member_id, category)
            );
            CREATE TABLE IF NOT EXISTS rule_proposals (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                run_id TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                category TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN ('open', 'active', 'rejected', 'changes_requested', 'superseded')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                activated_rule_id TEXT,
                revised_from_id TEXT REFERENCES rule_proposals(id)
            );
            CREATE TABLE IF NOT EXISTS rule_proposal_approvals (
                proposal_id TEXT NOT NULL REFERENCES rule_proposals(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                decision TEXT NOT NULL CHECK (decision IN ('pending', 'approved', 'rejected', 'changes_requested')),
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(proposal_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'note',
                created_at TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                recipient_id TEXT REFERENCES members(id) ON DELETE CASCADE,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id TEXT NOT NULL DEFAULT '',
                dedupe_key TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS board_post_versions (
                announcement_id TEXT NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                author_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                idempotency_key TEXT NOT NULL DEFAULT '',
                original_body TEXT NOT NULL,
                clarification_text TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Announcement',
                body TEXT NOT NULL,
                ai_status TEXT NOT NULL DEFAULT 'pending',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                requires_approval INTEGER NOT NULL DEFAULT 0,
                approval_status TEXT NOT NULL DEFAULT 'not_required',
                created_at TEXT NOT NULL,
                PRIMARY KEY(announcement_id, version)
            );
            CREATE TABLE IF NOT EXISTS announcement_approvals (
                announcement_id TEXT NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                decision TEXT NOT NULL CHECK(decision IN ('pending', 'approved', 'rejected', 'changes_requested')),
                note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(announcement_id, version, member_id)
            );
            CREATE TABLE IF NOT EXISTS house_board_agent_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                announcement_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                event TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                safe_detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS mediation_cases (
                id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL REFERENCES households(id) ON DELETE CASCADE,
                category TEXT NOT NULL,
                created_by TEXT NOT NULL REFERENCES members(id),
                identity_hidden INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                listening_summary TEXT NOT NULL DEFAULT '',
                listening_json TEXT NOT NULL DEFAULT '{}',
                mediation_json TEXT NOT NULL DEFAULT '{}',
                safety_guidance TEXT NOT NULL DEFAULT '',
                current_agreement_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(household_id, created_by, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS mediation_participants (
                case_id TEXT NOT NULL REFERENCES mediation_cases(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY(case_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS mediation_statements (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES mediation_cases(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id),
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(case_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS mediation_questions (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES mediation_cases(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mediation_clarification_responses (
                question_id TEXT NOT NULL REFERENCES mediation_questions(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id),
                answer TEXT NOT NULL DEFAULT '',
                marked_unknown INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY(question_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS mediation_agreements (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES mediation_cases(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                responsibilities_json TEXT NOT NULL,
                follow_up TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK(status IN ('pending', 'revision_required', 'active', 'superseded')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(case_id, version)
            );
            CREATE TABLE IF NOT EXISTS mediation_agreement_decisions (
                agreement_id TEXT NOT NULL REFERENCES mediation_agreements(id) ON DELETE CASCADE,
                member_id TEXT NOT NULL REFERENCES members(id),
                decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected', 'changes_requested')),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY(agreement_id, member_id)
            );
            CREATE TABLE IF NOT EXISTS mediation_agent_runs (
                run_id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES mediation_cases(id) ON DELETE CASCADE,
                agent_name TEXT NOT NULL,
                agent_version TEXT NOT NULL,
                operation TEXT NOT NULL,
                model TEXT NOT NULL,
                reasoning_effort TEXT NOT NULL,
                input_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                latency_ms INTEGER,
                outcome TEXT NOT NULL CHECK(outcome IN ('running', 'success', 'error')),
                input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_tokens INTEGER,
                request_id TEXT,
                error_code TEXT
            );
            CREATE TABLE IF NOT EXISTS mediation_agent_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES mediation_agent_runs(run_id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                event TEXT NOT NULL,
                tool_name TEXT,
                safe_detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, sequence)
            );
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_rule_preferences_household ON rule_preferences(household_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_rule_proposals_household ON rule_proposals(household_id, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mediation_cases_household ON mediation_cases(household_id, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mediation_runs_case ON mediation_agent_runs(case_id, started_at)")
        proposal_columns = {row[1] for row in db.execute("PRAGMA table_info(rule_proposals)")}
        if "revised_from_id" not in proposal_columns:
            db.execute("ALTER TABLE rule_proposals ADD COLUMN revised_from_id TEXT")
        announcement_columns = {row[1] for row in db.execute("PRAGMA table_info(announcements)")}
        announcement_migrations = {
            "original_body": "TEXT NOT NULL DEFAULT ''",
            "clarification_text": "TEXT NOT NULL DEFAULT ''",
            "post_type": "TEXT NOT NULL DEFAULT 'announcement'",
            "ai_status": "TEXT NOT NULL DEFAULT 'not_analyzed'",
            "analysis_json": "TEXT NOT NULL DEFAULT '{}'",
            "requires_approval": "INTEGER NOT NULL DEFAULT 0",
            "approval_status": "TEXT NOT NULL DEFAULT 'not_required'",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "idempotency_key": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in announcement_migrations.items():
            if column not in announcement_columns:
                db.execute(f"ALTER TABLE announcements ADD COLUMN {column} {definition}")
        notification_columns = {row[1] for row in db.execute("PRAGMA table_info(notifications)")}
        notification_migrations = {
            "recipient_id": "TEXT",
            "entity_type": "TEXT NOT NULL DEFAULT ''",
            "entity_id": "TEXT NOT NULL DEFAULT ''",
            "dedupe_key": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in notification_migrations.items():
            if column not in notification_columns:
                db.execute(f"ALTER TABLE notifications ADD COLUMN {column} {definition}")
        chore_columns = {row[1] for row in db.execute("PRAGMA table_info(chores)")}
        if "due_date" not in chore_columns:
            db.execute("ALTER TABLE chores ADD COLUMN due_date TEXT")
        expense_columns = {row[1] for row in db.execute("PRAGMA table_info(expenses)")}
        expense_migrations = {
            "amount_cents": "INTEGER",
            "due_date": "TEXT",
            "split_type": "TEXT NOT NULL DEFAULT 'equal'",
        }
        for column, definition in expense_migrations.items():
            if column not in expense_columns:
                db.execute(f"ALTER TABLE expenses ADD COLUMN {column} {definition}")
        db.execute("UPDATE announcements SET original_body = body WHERE original_body = ''")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_board_version_idempotency ON board_post_versions(household_id, author_id, idempotency_key) WHERE idempotency_key <> ''")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_dedupe ON notifications(household_id, recipient_id, dedupe_key) WHERE dedupe_key <> ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_board_posts_household ON announcements(household_id, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_board_approvals_member ON announcement_approvals(member_id, decision)")
        db.execute(
            """UPDATE board_post_versions
               SET approval_status = (
                   SELECT announcements.approval_status FROM announcements
                   WHERE announcements.id = board_post_versions.announcement_id
                     AND announcements.version = board_post_versions.version
               )
               WHERE EXISTS (
                   SELECT 1 FROM announcements
                   WHERE announcements.id = board_post_versions.announcement_id
                     AND announcements.version = board_post_versions.version
                     AND announcements.approval_status != board_post_versions.approval_status
               )"""
        )
        seed_demo(db)
        backfill_expense_shares(db)


def seed_demo(db: sqlite3.Connection) -> None:
    if db.execute("SELECT id FROM households WHERE id = ?", (DEMO_ID,)).fetchone():
        return
    created = now_iso()
    db.execute("INSERT INTO households (id, name, created_at) VALUES (?, ?, ?)", (DEMO_ID, "Willow House", created))
    members = [
        ("maya-chen", "Maya Chen", "The plant person", "sage"),
        ("eli-brooks", "Eli Brooks", "Early coffee, late playlists", "clay"),
        ("jordan-lee", "Jordan Lee", "Weekend pancake maker", "lavender"),
        ("chloe-martin", "Chloe Martin", "Keeps the house cozy", "butter"),
    ]
    db.executemany(
        "INSERT INTO members (id, household_id, name, bio, color, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [(mid, DEMO_ID, name, bio, color, created) for mid, name, bio, color in members],
    )
    db.executemany(
        "INSERT INTO announcements (id, household_id, author_id, category, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("ann-1", DEMO_ID, "maya-chen", "Heads-up", "Having a couple of friends over Friday around 8. We’ll keep the living room tidy and wrap up by 11 🌿", created),
            ("ann-2", DEMO_ID, "eli-brooks", "Reminder", "The building is doing a quick water shutoff tomorrow from 10–11 AM.", created),
            ("ann-3", DEMO_ID, "jordan-lee", "Little win", "Fresh coffee beans are on the counter — help yourself ☕", created),
        ],
    )
    db.executemany(
        "INSERT INTO chores (id, household_id, title, assignee_id, due_label, room, completed, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("chore-1", DEMO_ID, "Take bins to the curb", "eli-brooks", "Today", "Kitchen", 0, created),
            ("chore-2", DEMO_ID, "Water the balcony plants", "maya-chen", "Tomorrow", "Balcony", 0, created),
            ("chore-3", DEMO_ID, "Wipe down kitchen counters", "jordan-lee", "Yesterday", "Kitchen", 1, created),
            ("chore-4", DEMO_ID, "Restock dish soap", "chloe-martin", "Friday", "Kitchen", 0, created),
        ],
    )
    db.executemany(
        "INSERT INTO expenses (id, household_id, title, amount, due_label, status, payer_id, split_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("bill-1", DEMO_ID, "Internet · October", 68.00, "Due Oct 28", "Due soon", "maya-chen", json.dumps([17, 17, 17, 17]), created),
            ("bill-2", DEMO_ID, "Shared groceries", 42.60, "Settled Oct 19", "Settled", "jordan-lee", json.dumps([10.65] * 4), created),
        ],
    )
    db.executemany(
        "INSERT INTO house_rules (id, household_id, title, detail, category, approved, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
        [
            ("rule-1", DEMO_ID, "Quiet hours", "Weeknights after 10:30 PM; weekends after midnight.", "Being together", created),
            ("rule-2", DEMO_ID, "A heads-up for guests", "Let the house know before inviting a group over.", "Guests & shared space", created),
            ("rule-3", DEMO_ID, "Kitchen reset", "Leave counters clear and dishes in the dishwasher before bed.", "Keeping things tidy", created),
        ],
    )
    db.executemany(
        "INSERT INTO notifications (id, household_id, title, detail, kind, created_at, is_read) VALUES (?, ?, ?, ?, ?, ?, 0)",
        [
            ("notice-1", DEMO_ID, "A little Friday heads-up", "Maya shared plans for a few guests this Friday.", "board", created),
            ("notice-2", DEMO_ID, "One chore is ready for today", "Bins to the curb is on the list.", "chore", created),
        ],
    )


def cents_from_legacy(value: object) -> int:
    try:
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            return 0
        return int(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, ValueError, TypeError):
        return 0


def split_cents_equally(total_cents: int, member_ids: list[str]) -> list[int]:
    if not member_ids:
        return []
    base, remainder = divmod(total_cents, len(member_ids))
    return [base + (1 if index < remainder else 0) for index in range(len(member_ids))]


def backfill_expense_shares(db: sqlite3.Connection) -> None:
    """Upgrade older REAL-only expenses to cent-based shares without losing seed data."""
    for row in db.execute("SELECT * FROM expenses ORDER BY rowid").fetchall():
        total_cents = row["amount_cents"]
        if total_cents is None:
            total_cents = cents_from_legacy(row["amount"])
            db.execute("UPDATE expenses SET amount_cents = ? WHERE id = ?", (total_cents, row["id"]))
        already_migrated = db.execute(
            "SELECT 1 FROM expense_shares WHERE expense_id = ? LIMIT 1", (row["id"],)
        ).fetchone()
        if already_migrated:
            continue
        member_ids = [
            item["id"] for item in db.execute(
                "SELECT id FROM members WHERE household_id = ? ORDER BY rowid", (row["household_id"],)
            )
        ]
        try:
            legacy_split = json.loads(row["split_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            legacy_split = []
        shares = [cents_from_legacy(value) for value in legacy_split]
        if len(shares) != len(member_ids) or sum(shares) != total_cents:
            shares = split_cents_equally(total_cents, member_ids)
        paid_at = row["created_at"] if row["status"] == "Settled" else None
        for index, (member_id, amount_cents) in enumerate(zip(member_ids, shares)):
            # An unpaid legacy expense's payer advanced the full bill; their own share is settled.
            member_paid_at = paid_at or (row["created_at"] if member_id == row["payer_id"] else None)
            db.execute(
                """INSERT INTO expense_shares
                   (expense_id, member_id, amount_cents, paid_at, paid_by_member_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["id"], member_id, amount_cents, member_paid_at,
                 row["payer_id"] if member_paid_at else None),
            )
        update_expense_status(db, row["id"])


def update_expense_status(db: sqlite3.Connection, expense_id: str) -> None:
    counts = db.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN paid_at IS NOT NULL THEN 1 ELSE 0 END) AS paid
           FROM expense_shares WHERE expense_id = ?""",
        (expense_id,),
    ).fetchone()
    if not counts or counts["total"] == 0:
        return
    paid_count = counts["paid"] or 0
    status = "Settled" if paid_count == counts["total"] else "Partially paid" if paid_count else "Awaiting shares"
    db.execute("UPDATE expenses SET status = ? WHERE id = ?", (status, expense_id))


def household_payload(db: sqlite3.Connection, household_id: str, member_id: str | None = None) -> dict:
    household = db.execute("SELECT * FROM households WHERE id = ?", (household_id,)).fetchone()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    members = [dict(row) for row in db.execute("SELECT * FROM members WHERE household_id = ? ORDER BY rowid", (household_id,))]
    names = {member["id"]: member["name"] for member in members}
    announcements = [dict(row) for row in db.execute("SELECT * FROM announcements WHERE household_id = ? ORDER BY created_at DESC, rowid DESC", (household_id,))]
    chores = [dict(row) for row in db.execute("SELECT * FROM chores WHERE household_id = ? ORDER BY completed, rowid", (household_id,))]
    expenses = [dict(row) for row in db.execute("SELECT * FROM expenses WHERE household_id = ? ORDER BY rowid", (household_id,))]
    rules = [dict(row) for row in db.execute("SELECT * FROM house_rules WHERE household_id = ? AND approved = 1 ORDER BY rowid", (household_id,))]
    rule_preferences = [
        dict(row)
        for row in db.execute(
            """SELECT p.*, m.name AS member_name FROM rule_preferences p
               JOIN members m ON m.id = p.member_id
               WHERE p.household_id = ? ORDER BY p.updated_at DESC, p.rowid DESC""",
            (household_id,),
        )
    ]
    rule_proposals = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM rule_proposals WHERE household_id = ? ORDER BY created_at DESC, rowid DESC",
            (household_id,),
        )
    ]
    for proposal in rule_proposals:
        approvals = [
            dict(row)
            for row in db.execute(
                """SELECT a.member_id, m.name AS member_name, a.decision, a.note, a.updated_at
                   FROM rule_proposal_approvals a JOIN members m ON m.id = a.member_id
                   WHERE a.proposal_id = ? ORDER BY m.rowid""",
                (proposal["id"],),
            )
        ]
        proposal["approvals"] = approvals
        proposal["required_approvals"] = len(approvals)
        proposal["approved_count"] = sum(item["decision"] == "approved" for item in approvals)
    if member_id:
        valid_member = db.execute("SELECT 1 FROM members WHERE id = ? AND household_id = ?", (member_id, household_id)).fetchone()
        if valid_member is None:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")
        notifications = [dict(row) for row in db.execute(
            "SELECT * FROM notifications WHERE household_id = ? AND (recipient_id IS NULL OR recipient_id = ?) ORDER BY created_at DESC, rowid DESC LIMIT 50",
            (household_id, member_id),
        )]
    else:
        notifications = [dict(row) for row in db.execute(
            "SELECT * FROM notifications WHERE household_id = ? AND recipient_id IS NULL ORDER BY created_at DESC, rowid DESC LIMIT 50",
            (household_id,),
        )]
    for item in announcements:
        item["author_name"] = names.get(item["author_id"], "A roommate")
        item["original_body"] = item.get("original_body") or item["body"]
        try:
            item["analysis"] = json.loads(item.pop("analysis_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            item["analysis"] = {}
        version = int(item.get("version") or 1)
        approval_rows = [dict(row) for row in db.execute(
            """SELECT a.member_id, m.name AS member_name, a.decision, a.note, a.updated_at
               FROM announcement_approvals a JOIN members m ON m.id = a.member_id
               WHERE a.announcement_id = ? AND a.version = ? ORDER BY m.rowid""",
            (item["id"], version),
        )]
        item["approvals"] = approval_rows
        item["approved_count"] = sum(approval["decision"] == "approved" for approval in approval_rows)
        item["required_approvals"] = len(approval_rows)
        item["my_decision"] = next((approval["decision"] for approval in approval_rows if approval["member_id"] == member_id), None)
        item["requires_approval"] = bool(item.get("requires_approval"))
    for item in chores:
        item["assignee_name"] = names.get(item["assignee_id"], "Unassigned")
        item["completed"] = bool(item["completed"])
    balances = {member["id"]: {"member_id": member["id"], "member_name": member["name"], "owes_cents": 0, "owed_cents": 0, "net_cents": 0} for member in members}
    for item in expenses:
        item["payer_name"] = names.get(item["payer_id"], "A roommate")
        try:
            json.loads(item.pop("split_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            item.pop("split_json", None)
        item["amount_cents"] = int(item.get("amount_cents") or 0)
        item["amount"] = item["amount_cents"] / 100
        share_rows = [dict(row) for row in db.execute(
            """SELECT s.member_id, m.name AS member_name, s.amount_cents, s.paid_at, s.paid_by_member_id
               FROM expense_shares s JOIN members m ON m.id = s.member_id
               WHERE s.expense_id = ? ORDER BY m.rowid""",
            (item["id"],),
        )]
        item["participants"] = []
        item["participant_ids"] = []
        item["shares"] = []
        item["split"] = []
        item["outstanding_cents"] = 0
        for share in share_rows:
            amount_cents = int(share["amount_cents"])
            paid = share["paid_at"] is not None
            enriched = {
                "member_id": share["member_id"],
                "member_name": share["member_name"],
                "amount_cents": amount_cents,
                "amount": amount_cents / 100,
                "paid": paid,
                "paid_at": share["paid_at"],
                "paid_by_member_id": share["paid_by_member_id"],
            }
            item["shares"].append(enriched)
            item["participants"].append({"id": share["member_id"], "name": share["member_name"]})
            item["participant_ids"].append(share["member_id"])
            item["split"].append(amount_cents / 100)
            if not paid:
                item["outstanding_cents"] += amount_cents
                if share["member_id"] in balances:
                    balances[share["member_id"]]["owes_cents"] += amount_cents
                if item["payer_id"] in balances and share["member_id"] != item["payer_id"]:
                    balances[item["payer_id"]]["owed_cents"] += amount_cents
        item["status"] = "Settled" if item["outstanding_cents"] == 0 else "Partially paid" if any(s["paid"] for s in item["shares"]) else "Awaiting shares"
        for member_balance in balances.values():
            member_balance["net_cents"] = member_balance["owed_cents"] - member_balance["owes_cents"]
    expense_totals = {
        "outstanding_cents": sum(item["outstanding_cents"] for item in expenses),
        "settled_cents": sum(item["amount_cents"] for item in expenses if item["status"] == "Settled"),
        "recorded_cents": sum(item["amount_cents"] for item in expenses),
    }
    for item in notifications:
        item["is_read"] = bool(item["is_read"])
    return {
        "id": household["id"],
        "name": household["name"],
        "created_at": household["created_at"],
        "members": members,
        "announcements": announcements,
        "chores": chores,
        "expenses": expenses,
        "balances": list(balances.values()),
        "expense_totals": expense_totals,
        "rules": rules,
        "rule_preferences": rule_preferences,
        "rule_proposals": rule_proposals,
        "notifications": notifications,
    }


class HouseholdCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    members: list[str] = Field(min_length=1, max_length=8)

    @field_validator("name")
    @classmethod
    def clean_household_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Household name must contain at least two non-space characters")
        return value


class AnnouncementCreate(BaseModel):
    author_id: str
    body: str = Field(min_length=2, max_length=2_000)
    category: str = Field(default="Announcement", max_length=30)
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=100)

    @field_validator("body")
    @classmethod
    def clean_announcement_body(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Share a little more so your note is clear")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def validate_announcement_key(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,100}", value):
            raise ValueError("Invalid request key")
        return value


class ChoreUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    assignee_id: str | None = None
    due_date: date | None = None
    room: str | None = Field(default=None, min_length=1, max_length=50)
    completed: bool | None = None

    @field_validator("title", "room")
    @classmethod
    def clean_optional_chore_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class ChoreCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    assignee_id: str | None = None
    due_date: date | None = None
    room: str = Field(default="Home", min_length=1, max_length=50)

    @field_validator("title", "room")
    @classmethod
    def clean_chore_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


def validated_money(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0 or value > Decimal("1000000.00"):
        raise ValueError("Enter an amount greater than $0 and no more than $1,000,000")
    if value.as_tuple().exponent < -2:
        raise ValueError("Use no more than two decimal places")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_to_cents(value: Decimal) -> int:
    return int(validated_money(value) * 100)


class ExpenseShareInput(BaseModel):
    member_id: str
    amount: Decimal

    @field_validator("amount")
    @classmethod
    def validate_share_amount(cls, value: Decimal) -> Decimal:
        return validated_money(value)


class ExpenseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=100)
    amount: Decimal
    participant_ids: list[str] = Field(min_length=1, max_length=8)
    payer_id: str
    split_type: Literal["equal", "custom"] = "equal"
    custom_shares: list[ExpenseShareInput] = Field(default_factory=list, max_length=8)
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def clean_expense_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Expense name must contain at least two characters")
        return value

    @field_validator("amount")
    @classmethod
    def validate_expense_amount(cls, value: Decimal) -> Decimal:
        return validated_money(value)

    @field_validator("participant_ids")
    @classmethod
    def validate_participant_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Choose each roommate only once")
        return value

    @field_validator("custom_shares")
    @classmethod
    def validate_custom_share_ids(cls, value: list[ExpenseShareInput]) -> list[ExpenseShareInput]:
        ids = [item.member_id for item in value]
        if len(set(ids)) != len(ids):
            raise ValueError("Each roommate can have only one custom share")
        return value


class ExpenseSharePaid(BaseModel):
    member_id: str


class RulePreferenceSubmit(BaseModel):
    member_id: str
    category: str = Field(min_length=2, max_length=40)
    preference: str = Field(min_length=10, max_length=600)

    @field_validator("category")
    @classmethod
    def validate_rule_category(cls, value: str) -> str:
        value = value.strip()
        if value not in RULE_CATEGORIES:
            raise ValueError("Choose a supported household preference category")
        return value

    @field_validator("preference")
    @classmethod
    def clean_preference(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Share at least 10 characters so the preference is clear")
        return value


class RuleProposalGenerate(BaseModel):
    member_id: str


class RuleProposalDecision(BaseModel):
    member_id: str
    decision: Literal["approve", "reject", "request_changes"]
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return value.strip()


class RuleProposalRevision(BaseModel):
    member_id: str


@app.on_event("startup")
def on_startup() -> None:
    initialize_database()
    initialize_usage_logs()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "ai_model": AI_MODEL,
        "ai_enabled": bool(os.getenv("PORTKEY_API_KEY", "").strip()),
        "ai_reasoning_efforts": list(SUPPORTED_REASONING_EFFORTS),
    }


@app.get("/api/households/demo")
def get_demo_household(member_id: str | None = None) -> dict:
    with database() as db:
        return household_payload(db, DEMO_ID, member_id)


@app.get("/api/households/{household_id}")
def get_household(household_id: str, member_id: str | None = None) -> dict:
    with database() as db:
        return household_payload(db, household_id, member_id)


def rule_context(household_id: str) -> tuple[dict, list[dict], list[dict]]:
    with database() as db:
        household = db.execute("SELECT id, name FROM households WHERE id = ?", (household_id,)).fetchone()
        if household is None:
            raise HTTPException(status_code=404, detail="Household not found")
        members = [
            dict(row)
            for row in db.execute(
                "SELECT id, name FROM members WHERE household_id = ? ORDER BY rowid",
                (household_id,),
            )
        ]
        preferences = [
            dict(row)
            for row in db.execute(
                """SELECT p.member_id, m.name AS member_name, p.category, p.preference
                   FROM rule_preferences p JOIN members m ON m.id = p.member_id
                   WHERE p.household_id = ? ORDER BY p.category, m.rowid""",
                (household_id,),
            )
        ]
    return dict(household), members, preferences


def require_household_member(members: list[dict], member_id: str) -> None:
    if not any(member["id"] == member_id for member in members):
        raise HTTPException(status_code=403, detail="Choose a roommate in this household")


def agent_error_status(error: AIServiceError) -> int:
    if error.http_status == 429 or error.code == "rate_limited":
        return 429
    if error.code == "missing_api_key":
        return 503
    return 502


@app.post("/api/households/{household_id}/rules/preferences")
def save_rule_preference(household_id: str, payload: RulePreferenceSubmit) -> dict:
    _, members, _ = rule_context(household_id)
    require_household_member(members, payload.member_id)
    now = now_iso()
    with database() as db:
        db.execute(
            """INSERT INTO rule_preferences
               (id, household_id, member_id, category, preference, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(household_id, member_id, category) DO UPDATE SET
                   preference = excluded.preference, updated_at = excluded.updated_at""",
            (new_id(), household_id, payload.member_id, payload.category, payload.preference, now, now),
        )
    with database() as db:
        return household_payload(db, household_id)


@app.post("/api/households/{household_id}/rules/proposals/generate")
def create_rule_proposals(household_id: str, payload: RuleProposalGenerate) -> dict:
    household, members, preferences = rule_context(household_id)
    require_household_member(members, payload.member_id)
    contributors = {item["member_id"] for item in preferences}
    if len(contributors) < 2:
        raise HTTPException(status_code=409, detail="At least two roommates need to save preferences first")

    run_id = new_id()
    started = time.perf_counter()
    start_agent_run(
        run_id=run_id,
        household_id=household_id,
        agent_name=AGENT_NAME,
        agent_version=AGENT_VERSION,
        operation="generate_proposals",
        reasoning_effort=REASONING_EFFORT,
        participant_count=len(members),
        preference_count=len(preferences),
        category_summary=[item["category"] for item in preferences],
    )
    try:
        result, proposals = generate_proposals(
            run_id=run_id,
            household_name=household["name"],
            members=members,
            preferences=preferences,
        )
    except AIServiceError as error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=error.code,
        )
        raise HTTPException(status_code=agent_error_status(error), detail=str(error)) from None
    except RuleAgentOutputError as error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=error.code,
        )
        raise HTTPException(status_code=502, detail=str(error)) from None

    try:
        created = now_iso()
        with database() as db:
            current_member_ids = {
                row[0]
                for row in db.execute("SELECT id FROM members WHERE household_id = ?", (household_id,))
            }
            approver_ids = {member["id"] for member in members}
            if current_member_ids != approver_ids:
                raise HTTPException(status_code=409, detail="The household changed. Please generate proposals again.")
            for proposal in proposals:
                proposal_id = new_id()
                db.execute(
                    """INSERT INTO rule_proposals
                       (id, household_id, run_id, title, detail, category, rationale,
                        status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
                    (
                        proposal_id,
                        household_id,
                        run_id,
                        proposal["title"],
                        proposal["detail"],
                        proposal["category"],
                        proposal["rationale"],
                        created,
                        created,
                    ),
                )
                db.executemany(
                    """INSERT INTO rule_proposal_approvals
                       (proposal_id, member_id, decision, note, updated_at)
                       VALUES (?, ?, 'pending', '', ?)""",
                    [(proposal_id, member["id"], created) for member in members],
                )
    except HTTPException:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            result=result,
            proposal_count=0,
            error_code="household_changed",
        )
        raise
    except sqlite3.Error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            result=result,
            proposal_count=0,
            error_code="proposal_persistence_error",
        )
        raise HTTPException(status_code=500, detail="Could not save the AI proposals.") from None

    finish_agent_run(
        run_id=run_id,
        outcome="success",
        latency_ms=int((time.perf_counter() - started) * 1000),
        result=result,
        proposal_count=len(proposals),
    )
    with database() as db:
        return household_payload(db, household_id)


@app.post("/api/households/{household_id}/rules/proposals/{proposal_id}/decision")
def decide_rule_proposal(
    household_id: str,
    proposal_id: str,
    payload: RuleProposalDecision,
) -> dict:
    if payload.decision == "request_changes" and len(payload.note) < 10:
        raise HTTPException(status_code=422, detail="Add a short note describing the change you need")

    now = now_iso()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        proposal = db.execute(
            "SELECT * FROM rule_proposals WHERE id = ? AND household_id = ?",
            (proposal_id, household_id),
        ).fetchone()
        if proposal is None:
            raise HTTPException(status_code=404, detail="House-rule proposal not found")
        if proposal["status"] != "open":
            raise HTTPException(status_code=409, detail="This proposal is no longer accepting votes")
        approval = db.execute(
            "SELECT decision FROM rule_proposal_approvals WHERE proposal_id = ? AND member_id = ?",
            (proposal_id, payload.member_id),
        ).fetchone()
        if approval is None:
            raise HTTPException(status_code=403, detail="Only a roommate required to approve this rule can vote")
        if approval["decision"] != "pending":
            raise HTTPException(status_code=409, detail="Your response has already been recorded")

        decision_map = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}
        db.execute(
            """UPDATE rule_proposal_approvals SET decision = ?, note = ?, updated_at = ?
               WHERE proposal_id = ? AND member_id = ?""",
            (decision_map[payload.decision], payload.note, now, proposal_id, payload.member_id),
        )
        approvals = [
            dict(row)
            for row in db.execute(
                "SELECT member_id, decision FROM rule_proposal_approvals WHERE proposal_id = ?",
                (proposal_id,),
            )
        ]
        all_current_members = {
            row[0]
            for row in db.execute("SELECT id FROM members WHERE household_id = ?", (household_id,))
        }
        required_members = {item["member_id"] for item in approvals}

        if required_members != all_current_members or len(approvals) != len(all_current_members):
            raise HTTPException(status_code=409, detail="The approval list changed. Generate a fresh proposal.")
        if all(item["decision"] != "pending" for item in approvals):
            if any(item["decision"] == "rejected" for item in approvals):
                db.execute("UPDATE rule_proposals SET status = 'rejected', updated_at = ? WHERE id = ?", (now, proposal_id))
            elif any(item["decision"] == "changes_requested" for item in approvals):
                db.execute("UPDATE rule_proposals SET status = 'changes_requested', updated_at = ? WHERE id = ?", (now, proposal_id))
            elif all(item["decision"] == "approved" for item in approvals):
                rule_id = new_id()
                db.execute(
                    """INSERT INTO house_rules
                       (id, household_id, title, detail, category, approved, created_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?)""",
                    (rule_id, household_id, proposal["title"], proposal["detail"], proposal["category"], now),
                )
                db.execute(
                    """UPDATE rule_proposals SET status = 'active', activated_rule_id = ?, updated_at = ?
                       WHERE id = ?""",
                    (rule_id, now, proposal_id),
                )

    with database() as db:
        return household_payload(db, household_id)


@app.post("/api/households/{household_id}/rules/proposals/{proposal_id}/revise")
def revise_rule_proposal(
    household_id: str,
    proposal_id: str,
    payload: RuleProposalRevision,
) -> dict:
    household, members, preferences = rule_context(household_id)
    require_household_member(members, payload.member_id)
    with database() as db:
        proposal_row = db.execute(
            "SELECT * FROM rule_proposals WHERE id = ? AND household_id = ?",
            (proposal_id, household_id),
        ).fetchone()
        if proposal_row is None:
            raise HTTPException(status_code=404, detail="House-rule proposal not found")
        if proposal_row["status"] != "changes_requested":
            raise HTTPException(status_code=409, detail="This proposal has no requested changes to revise")
        requested_by = db.execute(
            """SELECT 1 FROM rule_proposal_approvals
               WHERE proposal_id = ? AND member_id = ? AND decision = 'changes_requested'""",
            (proposal_id, payload.member_id),
        ).fetchone()
        if requested_by is None:
            raise HTTPException(status_code=403, detail="A roommate who requested changes must start the revision")
        proposal = dict(proposal_row)
        change_requests = [
            dict(row)
            for row in db.execute(
                """SELECT m.name AS member_name, a.note FROM rule_proposal_approvals a
                   JOIN members m ON m.id = a.member_id
                   WHERE a.proposal_id = ? AND a.decision = 'changes_requested'""",
                (proposal_id,),
            )
        ]
        prior_approvers = [
            row[0]
            for row in db.execute(
                "SELECT member_id FROM rule_proposal_approvals WHERE proposal_id = ? ORDER BY rowid",
                (proposal_id,),
            )
        ]
    if set(prior_approvers) != {member["id"] for member in members}:
        raise HTTPException(status_code=409, detail="The household changed. Please create a new proposal.")

    run_id = new_id()
    started = time.perf_counter()
    start_agent_run(
        run_id=run_id,
        household_id=household_id,
        agent_name=AGENT_NAME,
        agent_version=AGENT_VERSION,
        operation="revise_proposal",
        reasoning_effort=REASONING_EFFORT,
        participant_count=len(members),
        preference_count=len(preferences),
        category_summary=[item["category"] for item in preferences],
    )
    try:
        result, revised = revise_proposal(
            run_id=run_id,
            household_name=household["name"],
            members=members,
            preferences=preferences,
            proposal=proposal,
            change_requests=change_requests,
        )
    except AIServiceError as error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=error.code,
        )
        raise HTTPException(status_code=agent_error_status(error), detail=str(error)) from None
    except RuleAgentOutputError as error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_code=error.code,
        )
        raise HTTPException(status_code=502, detail=str(error)) from None

    revised_id = new_id()
    created = now_iso()
    try:
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status FROM rule_proposals WHERE id = ? AND household_id = ?",
                (proposal_id, household_id),
            ).fetchone()
            if current is None or current["status"] != "changes_requested":
                raise HTTPException(status_code=409, detail="The original proposal changed while it was being revised")
            db.execute("UPDATE rule_proposals SET status = 'superseded', updated_at = ? WHERE id = ?", (created, proposal_id))
            db.execute(
                """INSERT INTO rule_proposals
                   (id, household_id, run_id, title, detail, category, rationale,
                    status, created_at, updated_at, revised_from_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
                (
                    revised_id,
                    household_id,
                    run_id,
                    revised["title"],
                    revised["detail"],
                    revised["category"],
                    revised["rationale"],
                    created,
                    created,
                    proposal_id,
                ),
            )
            db.executemany(
                """INSERT INTO rule_proposal_approvals
                   (proposal_id, member_id, decision, note, updated_at)
                   VALUES (?, ?, 'pending', '', ?)""",
                [(revised_id, member_id, created) for member_id in prior_approvers],
            )
    except HTTPException:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            result=result,
            error_code="proposal_changed",
        )
        raise
    except sqlite3.Error:
        finish_agent_run(
            run_id=run_id,
            outcome="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            result=result,
            error_code="revision_persistence_error",
        )
        raise HTTPException(status_code=500, detail="Could not save the revised proposal.") from None

    finish_agent_run(
        run_id=run_id,
        outcome="success",
        latency_ms=int((time.perf_counter() - started) * 1000),
        proposal_count=1,
        result=result,
    )
    with database() as db:
        return household_payload(db, household_id)


@app.post("/api/households")
def create_household(payload: HouseholdCreate) -> dict:
    household_id = new_id()
    created = now_iso()
    names = [name.strip() for name in payload.members]
    if any(len(name) < 1 or len(name) > 50 for name in names):
        raise HTTPException(status_code=422, detail="Roommate names must be between 1 and 50 characters")
    with database() as db:
        db.execute("INSERT INTO households (id, name, created_at) VALUES (?, ?, ?)", (household_id, payload.name.strip(), created))
        for index, name in enumerate(names):
            db.execute(
                "INSERT INTO members (id, household_id, name, role, bio, color, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_id(), household_id, name, "You" if index == 0 else "Roommate", "", ["sage", "clay", "lavender", "butter"][index % 4], created),
            )
    with database() as db:
        return household_payload(db, household_id)


@app.post("/api/households/{household_id}/announcements")
def create_announcement(household_id: str, payload: AnnouncementCreate) -> dict:
    return create_board_post(household_id, payload)


def due_label_for_date(due_date: date | None) -> str:
    return f"Due {due_date.strftime('%b')} {due_date.day}" if due_date else "No due date"


def household_member_ids(db: sqlite3.Connection, household_id: str) -> list[str]:
    household = db.execute("SELECT id FROM households WHERE id = ?", (household_id,)).fetchone()
    if household is None:
        raise HTTPException(status_code=404, detail="Household not found")
    return [row["id"] for row in db.execute(
        "SELECT id FROM members WHERE household_id = ? ORDER BY rowid", (household_id,)
    )]


@app.post("/api/households/{household_id}/chores")
def create_chore(household_id: str, payload: ChoreCreate, member_id: str | None = None) -> dict:
    chore_id = new_id()
    created = now_iso()
    with database() as db:
        members = household_member_ids(db, household_id)
        if member_id and member_id not in members:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")
        if payload.assignee_id and payload.assignee_id not in members:
            raise HTTPException(status_code=422, detail="Choose a roommate in this household")
        due_date = payload.due_date.isoformat() if payload.due_date else None
        db.execute(
            """INSERT INTO chores
               (id, household_id, title, assignee_id, due_label, due_date, room, completed, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (chore_id, household_id, payload.title, payload.assignee_id,
             due_label_for_date(payload.due_date), due_date, payload.room, created),
        )
    with database() as db:
        return household_payload(db, household_id, member_id)


@app.patch("/api/households/{household_id}/chores/{chore_id}")
def update_chore(household_id: str, chore_id: str, payload: ChoreUpdate, member_id: str | None = None) -> dict:
    with database() as db:
        row = db.execute(
            "SELECT id FROM chores WHERE id = ? AND household_id = ?", (chore_id, household_id)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Chore not found")
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=422, detail="Choose at least one chore field to update")
        members = household_member_ids(db, household_id)
        if member_id and member_id not in members:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")
        if "assignee_id" in changes and changes["assignee_id"] and changes["assignee_id"] not in members:
            raise HTTPException(status_code=422, detail="Choose a roommate in this household")
        if "due_date" in changes:
            selected_date = changes["due_date"]
            changes["due_date"] = selected_date.isoformat() if selected_date else None
            changes["due_label"] = due_label_for_date(selected_date)
        if "completed" in changes:
            changes["completed"] = int(changes["completed"])
        allowed = {"title", "assignee_id", "due_date", "due_label", "room", "completed"}
        assignments = ", ".join(f"{key} = ?" for key in changes if key in allowed)
        db.execute(
            f"UPDATE chores SET {assignments} WHERE id = ? AND household_id = ?",
            (*[changes[key] for key in changes if key in allowed], chore_id, household_id),
        )
    with database() as db:
        return household_payload(db, household_id, member_id)


@app.delete("/api/households/{household_id}/chores/{chore_id}")
def delete_chore(household_id: str, chore_id: str, member_id: str | None = None) -> dict:
    with database() as db:
        members = household_member_ids(db, household_id)
        if member_id and member_id not in members:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")
        result = db.execute(
            "DELETE FROM chores WHERE id = ? AND household_id = ?", (chore_id, household_id)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Chore not found")
    with database() as db:
        return household_payload(db, household_id, member_id)


@app.post("/api/households/{household_id}/expenses")
def create_expense(household_id: str, payload: ExpenseCreate, member_id: str | None = None) -> dict:
    expense_id = new_id()
    created = now_iso()
    total_cents = money_to_cents(payload.amount)
    with database() as db:
        all_member_ids = household_member_ids(db, household_id)
        if member_id and member_id not in all_member_ids:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")
        selected_ids = set(payload.participant_ids)
        if not selected_ids.issubset(set(all_member_ids)):
            raise HTTPException(status_code=422, detail="Choose participating roommates from this household")
        if payload.payer_id not in all_member_ids:
            raise HTTPException(status_code=422, detail="Choose a payer in this household")
        if payload.payer_id not in selected_ids:
            raise HTTPException(status_code=422, detail="The payer must be included as a participant")
        participant_ids = [member_id for member_id in all_member_ids if member_id in selected_ids]
        if payload.split_type == "equal":
            if payload.custom_shares:
                raise HTTPException(status_code=422, detail="Remove custom shares to split this expense equally")
            if total_cents < len(participant_ids):
                raise HTTPException(status_code=422, detail="Each participant must receive at least one cent")
            share_amounts = split_cents_equally(total_cents, participant_ids)
        else:
            custom_ids = {share.member_id for share in payload.custom_shares}
            if custom_ids != selected_ids or len(custom_ids) != len(payload.custom_shares):
                raise HTTPException(status_code=422, detail="Enter exactly one custom share for every participant")
            custom_cents = {share.member_id: money_to_cents(share.amount) for share in payload.custom_shares}
            if sum(custom_cents.values()) != total_cents:
                raise HTTPException(status_code=422, detail="Custom shares must add up to the expense total")
            share_amounts = [custom_cents[member_id] for member_id in participant_ids]
        due_date = payload.due_date.isoformat() if payload.due_date else None
        db.execute(
            """INSERT INTO expenses
               (id, household_id, title, amount, amount_cents, due_label, due_date, split_type,
                status, payer_id, split_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Awaiting shares', ?, ?, ?)""",
            (expense_id, household_id, payload.title, total_cents / 100, total_cents,
             due_label_for_date(payload.due_date), due_date, payload.split_type,
             payload.payer_id, json.dumps([value / 100 for value in share_amounts]), created),
        )
        db.executemany(
            """INSERT INTO expense_shares
               (expense_id, member_id, amount_cents, paid_at, paid_by_member_id)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (expense_id, member_id, amount_cents,
                 created if member_id == payload.payer_id else None,
                 payload.payer_id if member_id == payload.payer_id else None)
                for member_id, amount_cents in zip(participant_ids, share_amounts)
            ],
        )
        update_expense_status(db, expense_id)
    with database() as db:
        return household_payload(db, household_id, member_id)


@app.post("/api/households/{household_id}/expenses/{expense_id}/shares/{member_id}/paid")
def mark_expense_share_paid(
    household_id: str, expense_id: str, member_id: str, payload: ExpenseSharePaid
) -> dict:
    if payload.member_id != member_id:
        raise HTTPException(status_code=403, detail="You can only mark your own share as paid")
    with database() as db:
        members = household_member_ids(db, household_id)
        if member_id not in members:
            raise HTTPException(status_code=403, detail="Choose a roommate in this household")
        expense = db.execute(
            "SELECT id FROM expenses WHERE id = ? AND household_id = ?", (expense_id, household_id)
        ).fetchone()
        if expense is None:
            raise HTTPException(status_code=404, detail="Expense not found")
        share = db.execute(
            "SELECT paid_at FROM expense_shares WHERE expense_id = ? AND member_id = ?",
            (expense_id, member_id),
        ).fetchone()
        if share is None:
            raise HTTPException(status_code=403, detail="This roommate is not part of the expense")
        if share["paid_at"] is None:
            db.execute(
                "UPDATE expense_shares SET paid_at = ?, paid_by_member_id = ? WHERE expense_id = ? AND member_id = ? AND paid_at IS NULL",
                (now_iso(), member_id, expense_id, member_id),
            )
            update_expense_status(db, expense_id)
    with database() as db:
        return household_payload(db, household_id, member_id)


from backend.house_board_api import create_board_post, router as house_board_router
from backend.mediation_api import router as mediation_router

app.include_router(house_board_router)
app.include_router(mediation_router)
initialize_database()
initialize_usage_logs()
