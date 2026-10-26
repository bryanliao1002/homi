from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


_test_directory = tempfile.TemporaryDirectory(prefix="homi-phase23-tests-")
os.environ["HOMI_DATABASE_PATH"] = str(Path(_test_directory.name) / "isolated.sqlite")

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from backend.ai_service import AIResult  # noqa: E402
from backend import main  # noqa: E402
from backend.main import database  # noqa: E402
from backend import mediation_api  # noqa: E402
from backend.mediation_api import AgreementDecision, ClarificationSubmit, MemberAction, MediationCreate, StatementSubmit  # noqa: E402
from backend.mediation_agents import AgentResult  # noqa: E402


class DirectResponse:
    def __init__(self, status_code: int, data: dict):
        self.status_code = status_code
        self._data = data
        self.text = str(data)

    def json(self):
        return self._data


class DirectApiClient:
    """Dependency-free API adapter: exercises route functions without a TestClient extra."""
    def get(self, path: str):
        parsed = urlparse(path)
        parts = parsed.path.strip("/").split("/")
        try:
            if parts[0:2] == ["api", "households"] and parts[-1] == "mediations":
                member_id = parse_qs(parsed.query).get("member_id", [""])[0]
                data = mediation_api.list_mediations(parts[2], member_id)
                return DirectResponse(200, data)
            return DirectResponse(404, {"detail": "not found"})
        except HTTPException as error:
            return DirectResponse(error.status_code, {"detail": error.detail})

    def post(self, path: str, json: dict):
        parts = urlparse(path).path.strip("/").split("/")
        try:
            household_id = parts[2]
            if parts[3] == "mediations" and len(parts) == 4:
                data = mediation_api.create_mediation(household_id, MediationCreate(**json))
            else:
                case_id = parts[4]
                if parts[5] == "statements":
                    data = mediation_api.submit_statement(household_id, case_id, StatementSubmit(**json))
                elif parts[5] == "mediate":
                    data = mediation_api.create_mediation_analysis(household_id, case_id, MemberAction(**json))
                elif parts[5] == "listen":
                    data = mediation_api.retry_listening(household_id, case_id, MemberAction(**json))
                elif parts[5] == "clarifications":
                    data = mediation_api.respond_to_clarification(household_id, case_id, parts[6], ClarificationSubmit(**json))
                elif parts[5] == "agreements" and len(parts) == 6:
                    data = mediation_api.create_agreement(household_id, case_id, MemberAction(**json))
                elif parts[5] == "agreements" and parts[7] == "decision":
                    data = mediation_api.decide_agreement(household_id, case_id, parts[6], AgreementDecision(**json))
                elif parts[5] == "agreements" and parts[7] == "revise":
                    data = mediation_api.revise_agreement(household_id, case_id, parts[6], MemberAction(**json))
                else:
                    return DirectResponse(404, {"detail": "not found"})
            return DirectResponse(200, data)
        except HTTPException as error:
            return DirectResponse(error.status_code, {"detail": error.detail})
        except ValidationError as error:
            return DirectResponse(422, {"detail": str(error)})


class MediationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_database_path = main.DATABASE_PATH
        os.environ["HOMI_DATABASE_PATH"] = str(Path(_test_directory.name) / "isolated.sqlite")
        main.DATABASE_PATH = Path(os.environ["HOMI_DATABASE_PATH"])
        main.initialize_database()
        from backend.ai_service import initialize_usage_logs

        initialize_usage_logs()
        cls.client = DirectApiClient()

    @classmethod
    def tearDownClass(cls):
        main.DATABASE_PATH = cls.original_database_path
        _test_directory.cleanup()

    def setUp(self):
        with database() as db:
            db.execute("DELETE FROM mediation_cases")
        self.listen_calls = []
        self.mediate_calls = []
        self.agreement_calls = []
        self.ask_questions = False
        self.listen_patch = patch("backend.mediation_api.listen", side_effect=self.fake_listen)
        self.mediate_patch = patch("backend.mediation_api.mediate", side_effect=self.fake_mediate)
        self.agreement_patch = patch("backend.mediation_api.draft_agreement", side_effect=self.fake_agreement)
        self.listen_patch.start()
        self.mediate_patch.start()
        self.agreement_patch.start()
        self.addCleanup(self.listen_patch.stop)
        self.addCleanup(self.mediate_patch.stop)
        self.addCleanup(self.agreement_patch.stop)

    @staticmethod
    def result(output: dict) -> AgentResult:
        return AgentResult(
            result=AIResult(
                text="{}",
                model="gpt-6-luna",
                reasoning_effort="medium",
                input_tokens=None,
                output_tokens=None,
                reasoning_tokens=None,
                latency_ms=0,
                request_id=None,
            ),
            output=output,
        )

    def fake_listen(self, **kwargs):
        self.listen_calls.append(kwargs)
        return self.result({
            "neutral_summary": "Roommates would like a clearer, easier kitchen routine.",
            "reported_claims": ["A roommate reports dishes were left overnight."],
            "shared_information": ["Both roommates share the kitchen."],
            "unknowns": ["How often this occurs is not yet clear."],
            "clarification_questions": ["When would a kitchen reset feel practical?"] if self.ask_questions else [],
        })

    def fake_mediate(self, **kwargs):
        self.mediate_calls.append(kwargs)
        return self.result({
            "common_ground": ["Both roommates want a usable kitchen."],
            "concerns": ["The current timing expectation is unclear."],
            "reported_claims": ["One roommate reports dishes remained overnight."],
            "supported_information": ["Both use the shared kitchen."],
            "uncertainties": ["Frequency and timing have not been independently established."],
            "rule_analysis": [{"rule_id": "rule-3", "relationship": "The approved kitchen reset rule is relevant context, not proof of who did what."}],
            "proposed_resolution": "Try a shared evening reset, with each roommate handling their own dishes before bed for one week, then check whether the timing works for both.",
        })

    def fake_agreement(self, **kwargs):
        self.agreement_calls.append(kwargs)
        return self.result({
            "title": "A one-week kitchen reset",
            "summary": "Try a simple, shared evening routine for one week and check in together afterward.",
            "responsibilities": [
                {"participant_id": "p1", "action": "Rinse and place your dishes in the dishwasher after use.", "deadline": "Before bed"},
                {"participant_id": "p2", "action": "Load any shared cookware you used and leave the counters clear.", "deadline": "Before bed"},
            ],
            "follow_up": "Check in together after seven days and adjust the routine if needed.",
        })

    def create_case(self, *, key="test-case-key-001", statement="I have noticed Eli Brooks's dishes left in the sink overnight, and I would like us to agree on a routine.", category="Dishes & cleanliness"):
        response = self.client.post("/api/households/willow-house-demo/mediations", json={
            "member_id": "maya-chen",
            "other_member_ids": ["eli-brooks"],
            "category": category,
            "statement": statement,
            "hide_identity": True,
            "idempotency_key": key,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def gather_both(self, case, *, eli_statement="I sometimes get home late and want to use the kitchen, but I can clean up before bed."):
        response = self.client.post(
            f"/api/households/willow-house-demo/mediations/{case['id']}/statements",
            json={"member_id": "eli-brooks", "statement": eli_statement},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def approve(self, case, agreement, member_id):
        return self.client.post(
            f"/api/households/willow-house-demo/mediations/{case['id']}/agreements/{agreement['id']}/decision",
            json={"member_id": member_id, "decision": "approve"},
        )

    def test_private_statements_clarifications_unanimous_activation_and_persistence(self):
        self.ask_questions = True
        case = self.create_case()
        case_id = case["id"]
        self.assertEqual(case["status"], "gathering")
        self.assertEqual(len(self.listen_calls), 1)

        idempotent = self.create_case()
        self.assertEqual(idempotent["id"], case_id)
        self.assertEqual(len(self.listen_calls), 1)

        eli_view = self.client.get(f"/api/households/willow-house-demo/mediations?member_id=eli-brooks").json()["cases"][0]
        self.assertEqual(eli_view["my_statement"], "")
        self.assertEqual(eli_view["participants"][0]["name"], "A roommate")
        self.assertNotIn("dishes left in the sink", str(eli_view))
        outsider = self.client.get(f"/api/households/willow-house-demo/mediations?member_id=jordan-lee")
        self.assertEqual(outsider.status_code, 200)
        self.assertEqual(outsider.json()["cases"], [])

        early = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/mediate", json={"member_id": "maya-chen"})
        self.assertEqual(early.status_code, 409)
        self.gather_both(case)
        with database() as db:
            question = db.execute("SELECT id FROM mediation_questions WHERE case_id = ? AND active = 1", (case_id,)).fetchone()[0]
        self.assertEqual(len(self.listen_calls), 2)

        eli_unknown = self.client.post(
            f"/api/households/willow-house-demo/mediations/{case_id}/clarifications/{question}",
            json={"member_id": "eli-brooks", "mark_unknown": True},
        )
        self.assertEqual(eli_unknown.status_code, 200)
        self.assertEqual(eli_unknown.json()["status"], "clarifications")
        maya_answer = self.client.post(
            f"/api/households/willow-house-demo/mediations/{case_id}/clarifications/{question}",
            json={"member_id": "maya-chen", "answer": "Before bedtime seems practical for me."},
        )
        self.assertEqual(maya_answer.status_code, 200)
        self.assertEqual(maya_answer.json()["status"], "ready")
        self.assertEqual(maya_answer.json()["questions"][0]["my_responded"], True)

        analysis = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/mediate", json={"member_id": "maya-chen"})
        self.assertEqual(analysis.status_code, 200, analysis.text)
        mediated = analysis.json()
        self.assertEqual(mediated["status"], "mediated")
        self.assertTrue(any(run["agent_name"] == "mediation" and run["reasoning_effort"] == "high" for run in mediated["agent_runs"]))
        self.assertTrue(any(rule["rule_id"] == "rule-3" for rule in mediated["mediation"]["rule_analysis"]))
        self.assertIn("retrieve_approved_house_rules", str(mediated["agent_runs"]))
        self.assertIn("rule-3", [rule["id"] for rule in self.mediate_calls[0]["active_rules"]])
        self.assertNotIn("Eli Brooks", json.dumps(self.mediate_calls[0]["perspectives"]))
        self.assertNotIn("Maya Chen", json.dumps(self.mediate_calls[0]["perspectives"]))

        draft = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements", json={"member_id": "maya-chen"})
        self.assertEqual(draft.status_code, 200, draft.text)
        pending = draft.json()
        self.assertEqual(pending["status"], "agreement_pending")
        agreement = pending["agreements"][0]
        self.assertEqual(agreement["status"], "pending")
        self.assertEqual(agreement["required_approvals"], 2)

        one_vote = self.approve(pending, agreement, "maya-chen")
        self.assertEqual(one_vote.status_code, 200)
        self.assertEqual(one_vote.json()["status"], "agreement_pending")
        duplicate_vote = self.approve(pending, agreement, "maya-chen")
        self.assertEqual(duplicate_vote.status_code, 409)
        outsider_vote = self.approve(pending, agreement, "jordan-lee")
        self.assertEqual(outsider_vote.status_code, 403)

        final_vote = self.approve(pending, agreement, "eli-brooks")
        self.assertEqual(final_vote.status_code, 200)
        self.assertEqual(final_vote.json()["status"], "active")
        self.assertEqual(final_vote.json()["agreements"][0]["status"], "active")
        refreshed = self.client.get(f"/api/households/willow-house-demo/mediations?member_id=maya-chen").json()["cases"][0]
        self.assertEqual(refreshed["status"], "active")
        self.assertEqual(refreshed["agreements"][0]["approved_count"], 2)

        with database() as db:
            logs = db.execute("SELECT COUNT(*) FROM ai_usage_logs WHERE agent_run_id IN (SELECT run_id FROM mediation_agent_runs WHERE case_id = ?)", (case_id,)).fetchone()[0]
            traces = db.execute("SELECT safe_detail_json FROM mediation_agent_traces WHERE run_id IN (SELECT run_id FROM mediation_agent_runs WHERE case_id = ?)", (case_id,)).fetchall()
        # Mocked unit tests intentionally do not record invented provider usage.
        self.assertEqual(logs, 0)
        self.assertNotIn("dishes left in the sink", str([row[0] for row in traces]))

    def test_modification_request_creates_fresh_approval_round(self):
        case = self.create_case(key="modification-case-001", category="Chores", statement="The bathroom chore has been missed a few times and I would like us to agree on a clearer handoff.")
        case = self.gather_both(case)
        case_id = case["id"]
        self.assertEqual(case["status"], "ready")
        mediated = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/mediate", json={"member_id": "maya-chen"}).json()
        pending = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements", json={"member_id": "maya-chen"}).json()
        first = pending["agreements"][0]
        change = self.client.post(
            f"/api/households/willow-house-demo/mediations/{case_id}/agreements/{first['id']}/decision",
            json={"member_id": "maya-chen", "decision": "request_changes", "note": "Please make the follow-up timing more specific."},
        )
        self.assertEqual(change.status_code, 200)
        self.assertEqual(change.json()["status"], "revision_required")
        self.assertEqual(change.json()["agreements"][0]["status"], "revision_required")

        unauthorized_revision = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements/{first['id']}/revise", json={"member_id": "eli-brooks"})
        self.assertEqual(unauthorized_revision.status_code, 403)
        revised = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements/{first['id']}/revise", json={"member_id": "maya-chen"})
        self.assertEqual(revised.status_code, 200, revised.text)
        revision_view = revised.json()
        self.assertEqual(revision_view["status"], "agreement_pending")
        self.assertEqual(revision_view["agreements"][0]["version"], 2)
        self.assertEqual([item["decision"] for item in revision_view["agreements"][0]["decisions"]], ["pending", "pending"])
        old_vote = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements/{first['id']}/decision", json={"member_id": "eli-brooks", "decision": "approve"})
        self.assertEqual(old_vote.status_code, 409)
        only_one = self.approve(revision_view, revision_view["agreements"][0], "maya-chen")
        self.assertEqual(only_one.json()["status"], "agreement_pending")
        all_approved = self.approve(revision_view, revision_view["agreements"][0], "eli-brooks")
        self.assertEqual(all_approved.json()["status"], "active")
        self.assertTrue(self.agreement_calls[-1]["previous"])

    def test_rejection_prevents_activation_and_requires_new_approvals(self):
        case = self.create_case(key="rejection-case-001", category="Noise & quiet", statement="We have different expectations about evening music and I would like a calmer shared routine.")
        case = self.gather_both(case)
        case_id = case["id"]
        self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/mediate", json={"member_id": "maya-chen"})
        pending = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements", json={"member_id": "maya-chen"}).json()
        first = pending["agreements"][0]
        rejection = self.client.post(
            f"/api/households/willow-house-demo/mediations/{case_id}/agreements/{first['id']}/decision",
            json={"member_id": "eli-brooks", "decision": "reject", "note": "This timing would not work for my evening schedule."},
        )
        self.assertEqual(rejection.status_code, 200)
        self.assertEqual(rejection.json()["status"], "revision_required")
        self.assertNotEqual(rejection.json()["agreements"][0]["status"], "active")
        revised = self.client.post(f"/api/households/willow-house-demo/mediations/{case_id}/agreements/{first['id']}/revise", json={"member_id": "eli-brooks"})
        self.assertEqual(revised.status_code, 200)
        self.assertEqual(revised.json()["agreements"][0]["version"], 2)
        self.assertEqual(revised.json()["agreements"][0]["approved_count"], 0)

    def test_safety_language_pauses_ai_and_perspectives_cannot_be_overwritten(self):
        calls_before = len(self.listen_calls)
        case = self.create_case(
            key="safety-case-001",
            statement="I feel unsafe because my roommate threatened to hurt me, and I need support.",
            category="Other",
        )
        self.assertEqual(case["status"], "safety_support")
        self.assertIn("paused AI mediation", case["safety_guidance"])
        self.assertEqual(len(self.listen_calls), calls_before)
        eli_view = self.client.get("/api/households/willow-house-demo/mediations?member_id=eli-brooks").json()["cases"][0]
        self.assertEqual(eli_view["my_statement"], "")
        self.assertNotIn("threatened to hurt me", str(eli_view))

        normal_case = self.create_case(key="immutability-case-001")
        duplicate = self.client.post(
            f"/api/households/willow-house-demo/mediations/{normal_case['id']}/statements",
            json={"member_id": "maya-chen", "statement": "A different statement trying to replace the first entry."},
        )
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__":
    unittest.main()
