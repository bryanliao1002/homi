from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import ssl
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

AI_MODEL = "gpt-6-luna"
PORTKEY_RESPONSES_URL = "https://api.portkey.ai/v1/responses"
SUPPORTED_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]

REQUEST_TIMEOUT_SECONDS = 25
MAX_INPUT_CHARACTERS = 12_000
MAX_MEDIATION_INPUT_CHARACTERS = 20_000
MAX_OUTPUT_TOKENS = 2_048
MAX_HOUSE_RULES_OUTPUT_TOKENS = 3_072
MAX_SMART_BOARD_OUTPUT_TOKENS = 3_072
MAX_MEDIATION_OUTPUT_TOKENS = 3_072
MAX_REQUESTS_PER_MINUTE = 6
RATE_WINDOW_SECONDS = 60
MAX_RESPONSE_BYTES = 2_000_000

_recent_calls: deque[float] = deque()
_rate_lock = threading.Lock()
_logger = logging.getLogger(__name__)


@contextmanager
def _managed_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path, timeout=5)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class AIServiceError(RuntimeError):
    """Safe-to-surface AI error; never contains a credential or raw provider body."""

    def __init__(self, message: str, code: str, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class AIResult:
    text: str
    model: str
    reasoning_effort: str
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    latency_ms: int
    request_id: str | None


def _database_path() -> Path:
    configured = os.getenv("HOMI_DATABASE_PATH")
    return Path(configured) if configured else ROOT / "backend" / "data" / "homi.sqlite"


def _safe_string(value: Any, limit: int = 100) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return re.sub(r"[^A-Za-z0-9_.:-]", "", value)[:limit] or None


def _token_count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def initialize_usage_logs() -> None:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _managed_connection(path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                agent_run_id TEXT,
                purpose TEXT NOT NULL,
                model TEXT NOT NULL,
                reasoning_effort TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_tokens INTEGER,
                latency_ms INTEGER NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('success', 'error')),
                http_status INTEGER,
                error_code TEXT,
                request_id TEXT
            )
            """
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(ai_usage_logs)")}
        if "agent_run_id" not in columns:
            db.execute("ALTER TABLE ai_usage_logs ADD COLUMN agent_run_id TEXT")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_usage_created_at ON ai_usage_logs(created_at)"
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_ai_usage_agent_run ON ai_usage_logs(agent_run_id)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_agent_runs (
                run_id TEXT PRIMARY KEY,
                household_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                agent_version TEXT NOT NULL,
                operation TEXT NOT NULL,
                requested_model TEXT NOT NULL,
                response_model TEXT,
                reasoning_effort TEXT NOT NULL,
                participant_count INTEGER NOT NULL,
                preference_count INTEGER NOT NULL,
                category_summary TEXT NOT NULL,
                proposal_count INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER,
                output_tokens INTEGER,
                reasoning_tokens INTEGER,
                request_id TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                latency_ms INTEGER,
                outcome TEXT NOT NULL CHECK (outcome IN ('running', 'success', 'error')),
                error_code TEXT
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_household ON ai_agent_runs(household_id, started_at)")


def _write_usage_log(
    *,
    purpose: str,
    model: str,
    reasoning_effort: str,
    usage: dict[str, Any] | None,
    latency_ms: int,
    outcome: str,
    http_status: int | None,
    error_code: str | None,
    request_id: str | None,
    agent_run_id: str | None = None,
) -> None:
    usage = usage or {}
    output_details = usage.get("output_tokens_details")
    reasoning_tokens = output_details.get("reasoning_tokens") if isinstance(output_details, dict) else None
    initialize_usage_logs()
    with _managed_connection(_database_path()) as db:
        db.execute(
            """
            INSERT INTO ai_usage_logs (
                created_at, agent_run_id, purpose, model, reasoning_effort, input_tokens,
                output_tokens, reasoning_tokens, latency_ms, outcome,
                http_status, error_code, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                _safe_string(agent_run_id, 80),
                _safe_string(purpose, 40) or "unknown",
                _safe_string(model) or AI_MODEL,
                _safe_string(reasoning_effort, 20) or "unknown",
                _token_count(usage.get("input_tokens")),
                _token_count(usage.get("output_tokens")),
                _token_count(reasoning_tokens),
                max(0, latency_ms),
                outcome,
                http_status,
                _safe_string(error_code, 80),
                _safe_string(request_id, 120),
            ),
        )


def start_agent_run(
    *,
    run_id: str,
    household_id: str,
    agent_name: str,
    agent_version: str,
    operation: str,
    reasoning_effort: str,
    participant_count: int,
    preference_count: int,
    category_summary: list[str],
) -> None:
    initialize_usage_logs()
    with _managed_connection(_database_path()) as db:
        db.execute(
            """
            INSERT INTO ai_agent_runs (
                run_id, household_id, agent_name, agent_version, operation,
                requested_model, reasoning_effort, participant_count, preference_count,
                category_summary, started_at, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')
            """,
            (
                run_id,
                _safe_string(household_id, 80) or "unknown",
                _safe_string(agent_name, 80) or "unknown",
                _safe_string(agent_version, 40) or "unknown",
                _safe_string(operation, 60) or "unknown",
                AI_MODEL,
                _safe_string(reasoning_effort, 20) or "unknown",
                max(0, participant_count),
                max(0, preference_count),
                json.dumps(sorted(set(category_summary)), ensure_ascii=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def finish_agent_run(
    *,
    run_id: str,
    outcome: Literal["success", "error"],
    latency_ms: int,
    proposal_count: int = 0,
    result: AIResult | None = None,
    error_code: str | None = None,
) -> None:
    initialize_usage_logs()
    with _managed_connection(_database_path()) as db:
        usage_row = db.execute(
            """
            SELECT model, input_tokens, output_tokens, reasoning_tokens, request_id, outcome
            FROM ai_usage_logs WHERE agent_run_id = ? ORDER BY id DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        response_model = result.model if result else (
            usage_row[0]
            if usage_row and (usage_row[5] == "success" or usage_row[1] is not None or usage_row[4])
            else None
        )
        input_tokens = result.input_tokens if result else (usage_row[1] if usage_row else None)
        output_tokens = result.output_tokens if result else (usage_row[2] if usage_row else None)
        reasoning_tokens = result.reasoning_tokens if result else (usage_row[3] if usage_row else None)
        request_id = result.request_id if result else (usage_row[4] if usage_row else None)
        db.execute(
            """
            UPDATE ai_agent_runs
            SET response_model = ?, input_tokens = ?, output_tokens = ?,
                reasoning_tokens = ?, request_id = ?, proposal_count = ?,
                completed_at = ?, latency_ms = ?, outcome = ?, error_code = ?
            WHERE run_id = ?
            """,
            (
                _safe_string(response_model),
                _token_count(input_tokens),
                _token_count(output_tokens),
                _token_count(reasoning_tokens),
                _safe_string(request_id, 120),
                max(0, proposal_count),
                datetime.now(timezone.utc).isoformat(),
                max(0, latency_ms),
                outcome,
                _safe_string(error_code, 80),
                run_id,
            ),
        )


def _reserve_rate_slot() -> None:
    now = time.monotonic()
    with _rate_lock:
        while _recent_calls and now - _recent_calls[0] >= RATE_WINDOW_SECONDS:
            _recent_calls.popleft()
        if len(_recent_calls) >= MAX_REQUESTS_PER_MINUTE:
            raise AIServiceError("AI request limit reached. Please retry in a minute.", "rate_limited", 429)
        _recent_calls.append(now)


def _tls_context() -> ssl.SSLContext:
    configured_bundle = os.getenv("SSL_CERT_FILE")
    candidates = [
        configured_bundle,
        ssl.get_default_verify_paths().cafile,
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def _extract_text(response: dict[str, Any]) -> str:
    direct_text = response.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    chunks: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
    return "\n".join(chunks).strip()


def _provider_error_code(error: HTTPError) -> str:
    try:
        body = error.read(64_000)
        body_text = body.decode("utf-8", errors="replace")
        if "error 1010" in body_text.lower() and "cloudflare" in body_text.lower():
            return "cloudflare_1010"
        payload = json.loads(body_text)
        provider_error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(provider_error, dict):
            code = _safe_string(provider_error.get("code"), 80)
            error_type = _safe_string(provider_error.get("type"), 80)
            label = code or error_type
            param = _safe_string(provider_error.get("param"), 80)
            if label and param:
                return f"{label}:{param}"
            message = provider_error.get("message")
            if label and isinstance(message, str):
                normalized = message.casefold()
                fields = ("instructions", "max_output_tokens", "reasoning", "text", "input", "model", "store")
                field = next((name for name in fields if name in normalized), None)
                if field:
                    return f"{label}:{field}"
            if code:
                return code
            if error_type:
                return error_type
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        pass
    return f"http_{error.code}"


def _post_response(payload: dict[str, Any], api_key: str) -> tuple[dict[str, Any], int, str | None]:
    request = Request(
        PORTKEY_RESPONSES_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "homi-backend/0.2",
            "x-portkey-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=_tls_context()) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AIServiceError("AI response exceeded the size limit.", "response_too_large", response.status)
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise AIServiceError("Portkey returned an invalid JSON response.", "invalid_response_json", response.status) from None
            if not isinstance(decoded, dict):
                raise AIServiceError("Portkey returned an invalid response.", "invalid_response_shape", response.status)
            request_id = _safe_string(response.headers.get("x-portkey-trace-id") or response.headers.get("x-request-id"), 120)
            return decoded, response.status, request_id
    except HTTPError as error:
        raise AIServiceError(
            "Portkey rejected the AI request.",
            _provider_error_code(error),
            error.code,
        ) from None
    except (TimeoutError, URLError) as error:
        reason = getattr(error, "reason", None)
        if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
            raise AIServiceError("Portkey request timed out.", "request_timeout", 504) from None
        raise AIServiceError("Could not reach Portkey.", "network_error", 502) from None
    except OSError:
        raise AIServiceError("Could not reach Portkey.", "network_error", 502) from None


class AIService:
    """Reusable, backend-only client for the course Portkey gateway."""

    def generate(
        self,
        prompt: str,
        *,
        purpose: Literal["verification", "house_rules", "smart_board", "ai_judge"],
        reasoning_effort: ReasoningEffort = "medium",
        max_output_tokens: int = 512,
        instructions: str | None = None,
        json_mode: bool = False,
        agent_run_id: str | None = None,
    ) -> AIResult:
        started = time.perf_counter()
        usage: dict[str, Any] | None = None
        model = AI_MODEL
        request_id: str | None = None
        http_status: int | None = None

        try:
            if not isinstance(prompt, str) or not prompt.strip():
                raise AIServiceError("Prompt must not be empty.", "invalid_prompt", 422)
            input_limit = MAX_MEDIATION_INPUT_CHARACTERS if purpose == "ai_judge" else MAX_INPUT_CHARACTERS
            if len(prompt) > input_limit:
                raise AIServiceError("Prompt exceeds the size limit.", "prompt_too_large", 413)
            if instructions is not None and (not isinstance(instructions, str) or len(instructions) > 4_000):
                raise AIServiceError("Instructions exceed the size limit.", "instructions_too_large", 413)
            if reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
                raise AIServiceError("Unsupported reasoning effort.", "invalid_reasoning_effort", 422)
            output_token_limit = {
                "house_rules": MAX_HOUSE_RULES_OUTPUT_TOKENS,
                "smart_board": MAX_SMART_BOARD_OUTPUT_TOKENS,
                "ai_judge": MAX_MEDIATION_OUTPUT_TOKENS,
            }.get(purpose, MAX_OUTPUT_TOKENS)
            if isinstance(max_output_tokens, bool) or not 1 <= max_output_tokens <= output_token_limit:
                raise AIServiceError(
                    f"Output token limit must be between 1 and {output_token_limit}.",
                    "invalid_token_limit",
                    422,
                )

            api_key = os.getenv("PORTKEY_API_KEY", "").strip()
            if not api_key:
                raise AIServiceError("PORTKEY_API_KEY is not configured on the backend.", "missing_api_key", 503)

            _reserve_rate_slot()
            payload: dict[str, Any] = {
                "model": AI_MODEL,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt.strip()}],
                    }
                ],
                "reasoning": {"effort": reasoning_effort},
                "max_output_tokens": max_output_tokens,
                "store": False,
            }
            if instructions:
                payload["instructions"] = instructions
            if json_mode:
                payload["text"] = {"format": {"type": "json_object"}}
            response, http_status, request_id = _post_response(payload, api_key)
            usage_data = response.get("usage")
            usage = usage_data if isinstance(usage_data, dict) else None
            model = _safe_string(response.get("model")) or AI_MODEL
            response_status = response.get("status")
            if response_status not in (None, "completed"):
                incomplete_details = response.get("incomplete_details")
                incomplete_reason = (
                    incomplete_details.get("reason")
                    if isinstance(incomplete_details, dict)
                    else None
                )
                reported_output_tokens = _token_count(usage.get("output_tokens")) if usage else None
                budget_exhausted = incomplete_reason == "max_output_tokens" or (
                    incomplete_reason is None
                    and reported_output_tokens is not None
                    and reported_output_tokens >= max_output_tokens
                )
                error_code = "output_limit_reached" if budget_exhausted else "incomplete_response"
                raise AIServiceError("The model did not complete the response.", error_code, http_status)
            text = _extract_text(response)
            if not text:
                raise AIServiceError("Portkey returned no text output.", "empty_response", http_status)

            latency_ms = int((time.perf_counter() - started) * 1000)
            result = AIResult(
                text=text,
                model=model,
                reasoning_effort=reasoning_effort,
                input_tokens=_token_count(usage.get("input_tokens")) if usage else None,
                output_tokens=_token_count(usage.get("output_tokens")) if usage else None,
                reasoning_tokens=(
                    _token_count(usage.get("output_tokens_details", {}).get("reasoning_tokens"))
                    if usage and isinstance(usage.get("output_tokens_details"), dict)
                    else None
                ),
                latency_ms=latency_ms,
                request_id=request_id or _safe_string(response.get("id"), 120),
            )
            _write_usage_log(
                purpose=purpose,
                model=model,
                reasoning_effort=reasoning_effort,
                usage=usage,
                latency_ms=latency_ms,
                outcome="success",
                http_status=http_status,
                error_code=None,
                request_id=result.request_id,
                agent_run_id=agent_run_id,
            )
            return result
        except AIServiceError as error:
            latency_ms = int((time.perf_counter() - started) * 1000)
            try:
                _write_usage_log(
                    purpose=purpose,
                    model=model,
                    reasoning_effort=str(reasoning_effort),
                    usage=usage,
                    latency_ms=latency_ms,
                    outcome="error",
                    http_status=error.http_status or http_status,
                    error_code=error.code,
                    request_id=request_id,
                    agent_run_id=agent_run_id,
                )
            except sqlite3.Error as log_error:
                _logger.error("Could not persist AI usage metadata (%s)", type(log_error).__name__)
            raise
        except Exception as error:
            latency_ms = int((time.perf_counter() - started) * 1000)
            try:
                _write_usage_log(
                    purpose=purpose,
                    model=model,
                    reasoning_effort=str(reasoning_effort),
                    usage=usage,
                    latency_ms=latency_ms,
                    outcome="error",
                    http_status=http_status,
                    error_code="internal_error",
                    request_id=request_id,
                    agent_run_id=agent_run_id,
                )
            except sqlite3.Error as log_error:
                _logger.error("Could not persist AI usage metadata (%s)", type(log_error).__name__)
            _logger.error("Unexpected AI service failure (%s)", type(error).__name__)
            raise AIServiceError("Unexpected AI service error.", "internal_error", 500) from None
