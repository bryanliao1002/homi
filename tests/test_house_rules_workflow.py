from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend import main
from backend.ai_service import AIResult, initialize_usage_logs


class HouseRulesWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="homi-phase31-rules-")
        cls.original_database_path = main.DATABASE_PATH
        cls.database_path = Path(cls.temp_dir.name) / "isolated.sqlite"
        os.environ["HOMI_DATABASE_PATH"] = str(cls.database_path)
        main.DATABASE_PATH = cls.database_path
        main.initialize_database()
        initialize_usage_logs()

    @classmethod
    def tearDownClass(cls):
        main.DATABASE_PATH = cls.original_database_path
        cls.temp_dir.cleanup()

    def setUp(self):
        self.household = main.create_household(main.HouseholdCreate(
            name="Test Home",
            members=["Maya Example", "Eli Example", "Jordan Example"],
        ))
        self.household_id = self.household["id"]
        self.member_ids = [member["id"] for member in self.household["members"]]
        self.generated = [{
            "title": "A calmer evening kitchen",
            "detail": "After using the kitchen, each person rinses their dishes and clears their own items before bed.",
            "category": "Cleanliness",
            "rationale": "Roommates prefer a usable shared kitchen and a routine that works with different schedules.",
        }]
        self.revised = {
            **self.generated[0],
            "detail": "After using the kitchen, each person rinses their dishes and clears their own items by 10 AM the next day.",
        }
        self.generate_patch = patch(
            "backend.main.generate_proposals",
            return_value=(self.ai_result("high"), self.generated),
        )
        self.revise_patch = patch(
            "backend.main.revise_proposal",
            return_value=(self.ai_result("high"), self.revised),
        )
        self.generate_mock = self.generate_patch.start()
        self.revise_mock = self.revise_patch.start()
        self.addCleanup(self.generate_patch.stop)
        self.addCleanup(self.revise_patch.stop)

    @staticmethod
    def ai_result(effort: str) -> AIResult:
        return AIResult(
            text="{}", model="gpt-6-luna", reasoning_effort=effort,
            input_tokens=10, output_tokens=20, reasoning_tokens=5,
            latency_ms=12, request_id=None,
        )

    def save_preference(self, member_id: str, preference: str):
        return main.save_rule_preference(
            self.household_id,
            main.RulePreferenceSubmit(
                member_id=member_id,
                category="Cleanliness",
                preference=preference,
            ),
        )

    def generate(self):
        return main.create_rule_proposals(
            self.household_id,
            main.RuleProposalGenerate(member_id=self.member_ids[0]),
        )

    def decide(self, proposal_id: str, member_id: str, decision: str, note: str = ""):
        return main.decide_rule_proposal(
            self.household_id,
            proposal_id,
            main.RuleProposalDecision(member_id=member_id, decision=decision, note=note),
        )

    def proposal(self, payload: dict, proposal_id: str | None = None) -> dict:
        return next(
            item for item in payload["rule_proposals"]
            if proposal_id is None or item["id"] == proposal_id
        )

    def test_preferences_upsert_and_rule_activates_only_after_unanimous_approval(self):
        self.save_preference(self.member_ids[0], "Please leave the kitchen ready for the next person.")
        self.save_preference(self.member_ids[0], "I can clean up by the next morning after a late night.")
        self.save_preference(self.member_ids[1], "I want counters clear and dishes rinsed after cooking.")

        with main.database() as db:
            preference_count = db.execute(
                "SELECT COUNT(*) FROM rule_preferences WHERE household_id = ?",
                (self.household_id,),
            ).fetchone()[0]
        self.assertEqual(preference_count, 2, "Editing a preference should update its category row, not duplicate it")

        payload = self.generate()
        self.generate_mock.assert_called_once()
        saved_preferences = self.generate_mock.call_args.kwargs["preferences"]
        self.assertIn("I can clean up by the next morning after a late night.", [item["preference"] for item in saved_preferences])
        with main.database() as db:
            run_effort = db.execute(
                "SELECT reasoning_effort FROM ai_agent_runs WHERE household_id = ? AND agent_name = 'house_rules' ORDER BY started_at DESC LIMIT 1",
                (self.household_id,),
            ).fetchone()[0]
        self.assertEqual(run_effort, "high")

        proposal = self.proposal(payload)
        proposal_id = proposal["id"]
        self.assertEqual(proposal["required_approvals"], 3)
        self.assertEqual({item["decision"] for item in proposal["approvals"]}, {"pending"})
        with self.assertRaises(HTTPException) as outsider:
            self.decide(proposal_id, "someone-else", "approve")
        self.assertEqual(outsider.exception.status_code, 403)

        first = self.decide(proposal_id, self.member_ids[0], "approve")
        self.assertEqual(self.proposal(first, proposal_id)["status"], "open")
        self.assertEqual(first["rules"], [])
        with self.assertRaises(HTTPException) as duplicate:
            self.decide(proposal_id, self.member_ids[0], "approve")
        self.assertEqual(duplicate.exception.status_code, 409)

        second = self.decide(proposal_id, self.member_ids[1], "approve")
        self.assertEqual(self.proposal(second, proposal_id)["status"], "open")
        self.assertEqual(second["rules"], [])
        final = self.decide(proposal_id, self.member_ids[2], "approve")
        activated = self.proposal(final, proposal_id)
        self.assertEqual(activated["status"], "active")
        self.assertEqual(activated["approved_count"], 3)
        self.assertEqual(len(final["rules"]), 1)
        self.assertEqual(final["rules"][0]["id"], activated["activated_rule_id"])

    def test_change_request_revision_resets_votes_and_rejection_never_activates(self):
        self.save_preference(self.member_ids[0], "I prefer to reset shared surfaces before bedtime.")
        self.save_preference(self.member_ids[1], "I need flexibility if I get home after the evening shift.")
        generated = self.generate()
        original = self.proposal(generated)
        original_id = original["id"]

        self.decide(original_id, self.member_ids[0], "approve")
        self.decide(original_id, self.member_ids[1], "request_changes", "Please allow late arrivals to clean up the next morning.")
        changed = self.decide(original_id, self.member_ids[2], "approve")
        self.assertEqual(self.proposal(changed, original_id)["status"], "changes_requested")
        self.assertEqual(changed["rules"], [])

        with self.assertRaises(HTTPException) as unauthorized_revision:
            main.revise_rule_proposal(
                self.household_id, original_id,
                main.RuleProposalRevision(member_id=self.member_ids[0]),
            )
        self.assertEqual(unauthorized_revision.exception.status_code, 403)

        revised_payload = main.revise_rule_proposal(
            self.household_id, original_id,
            main.RuleProposalRevision(member_id=self.member_ids[1]),
        )
        self.revise_mock.assert_called_once()
        revised = self.proposal(revised_payload)
        prior = self.proposal(revised_payload, original_id)
        self.assertEqual(prior["status"], "superseded")
        with self.assertRaises(HTTPException) as stale_approval:
            self.decide(original_id, self.member_ids[2], "approve")
        self.assertEqual(stale_approval.exception.status_code, 409)
        self.assertEqual(revised["revised_from_id"], original_id)
        self.assertEqual(revised["status"], "open")
        self.assertEqual(revised["approved_count"], 0)
        self.assertEqual({item["decision"] for item in revised["approvals"]}, {"pending"})
        self.assertEqual(revised_payload["rules"], [])

        revised_id = revised["id"]
        self.decide(revised_id, self.member_ids[0], "reject", "This arrangement does not work for me.")
        self.decide(revised_id, self.member_ids[1], "approve")
        rejected = self.decide(revised_id, self.member_ids[2], "approve")
        self.assertEqual(self.proposal(rejected, revised_id)["status"], "rejected")
        self.assertEqual(rejected["rules"], [])

    def test_household_preferences_and_chore_updates_are_scoped_and_persisted(self):
        other = main.create_household(main.HouseholdCreate(name="Other Place", members=["Nina Example"]))
        with self.assertRaises(HTTPException) as cross_household_preference:
            main.save_rule_preference(
                self.household_id,
                main.RulePreferenceSubmit(
                    member_id=other["members"][0]["id"],
                    category="Cleanliness",
                    preference="I would like to keep shared counters clear.",
                ),
            )
        self.assertEqual(cross_household_preference.exception.status_code, 403)

        with main.database() as db:
            db.execute(
                "INSERT INTO chores (id, household_id, title, assignee_id, due_label, room, completed, created_at) VALUES ('test-chore', ?, 'Reset the counters', ?, 'Today', 'Kitchen', 0, 'now')",
                (self.household_id, self.member_ids[0]),
            )
        chore = next(item for item in main.get_household(self.household_id)["chores"] if item["id"] == "test-chore")
        updated = main.update_chore(self.household_id, chore["id"], main.ChoreUpdate(completed=True))
        stored = next(item for item in updated["chores"] if item["id"] == chore["id"])
        self.assertTrue(stored["completed"])
        reloaded = main.get_household(self.household_id)
        self.assertTrue(next(item for item in reloaded["chores"] if item["id"] == chore["id"])["completed"])
        with self.assertRaises(HTTPException) as foreign_chore:
            main.update_chore(other["id"], chore["id"], main.ChoreUpdate(completed=True))
        self.assertEqual(foreign_chore.exception.status_code, 404)
        self.assertEqual(reloaded["expenses"], [])
        self.assertEqual(main.get_household(other["id"])["chores"], [])

    def test_rule_generation_requires_two_contributors_and_keeps_households_separate(self):
        self.save_preference(self.member_ids[0], "I like the kitchen cleaned after each meal.")
        with self.assertRaises(HTTPException) as insufficient:
            self.generate()
        self.assertEqual(insufficient.exception.status_code, 409)
        self.generate_mock.assert_not_called()

        other = main.create_household(main.HouseholdCreate(name="Other Place", members=["Nina Example"]))
        other_payload = main.get_household(other["id"])
        self.assertEqual(other_payload["rule_preferences"], [])
        self.assertEqual(other_payload["rule_proposals"], [])
        self.assertEqual(other_payload["rules"], [])


if __name__ == "__main__":
    unittest.main()
