from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from backend import main


class HouseholdBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="homi-phase34-")
        cls.original_database_path = main.DATABASE_PATH
        cls.database_path = Path(cls.temp_dir.name) / "phase34.sqlite"
        os.environ["HOMI_DATABASE_PATH"] = str(cls.database_path)
        main.DATABASE_PATH = cls.database_path
        main.initialize_database()

    @classmethod
    def tearDownClass(cls):
        main.DATABASE_PATH = cls.original_database_path
        cls.temp_dir.cleanup()

    def setUp(self):
        main.DATABASE_PATH = self.database_path
        self.household = main.create_household(main.HouseholdCreate(
            name="Juniper House", members=["Avery Example", "Sam Example", "Riley Example"]
        ))
        self.household_id = self.household["id"]
        self.member_ids = [member["id"] for member in self.household["members"]]

    def test_chore_create_edit_completion_delete_and_persistence(self):
        chore = main.create_chore(self.household_id, main.ChoreCreate(
            title="  Sweep the entry  ", assignee_id=self.member_ids[1],
            due_date="2026-11-02", room="Entry",
        ))
        saved = next(item for item in chore["chores"] if item["title"] == "Sweep the entry")
        self.assertEqual(saved["assignee_id"], self.member_ids[1])
        self.assertEqual(saved["due_date"], "2026-11-02")
        self.assertEqual(saved["room"], "Entry")

        edited = main.update_chore(self.household_id, saved["id"], main.ChoreUpdate(
            title="Reset the entry", assignee_id=self.member_ids[2],
            due_date="2026-11-03", completed=True,
        ))
        updated = next(item for item in edited["chores"] if item["id"] == saved["id"])
        self.assertEqual(updated["title"], "Reset the entry")
        self.assertEqual(updated["assignee_id"], self.member_ids[2])
        self.assertTrue(updated["completed"])
        persisted = main.get_household(self.household_id)
        self.assertEqual(next(item for item in persisted["chores"] if item["id"] == saved["id"])["due_date"], "2026-11-03")

        deleted = main.delete_chore(self.household_id, saved["id"])
        self.assertNotIn(saved["id"], {item["id"] for item in deleted["chores"]})
        with self.assertRaises(HTTPException) as missing:
            main.delete_chore(self.household_id, saved["id"])
        self.assertEqual(missing.exception.status_code, 404)

    def test_chore_assignment_and_household_isolation(self):
        other = main.create_household(main.HouseholdCreate(name="Other Home", members=["Casey Other"]))
        with self.assertRaises(HTTPException) as foreign_assignee:
            main.create_chore(self.household_id, main.ChoreCreate(
                title="Water plants", assignee_id=other["members"][0]["id"]
            ))
        self.assertEqual(foreign_assignee.exception.status_code, 422)

        created = main.create_chore(self.household_id, main.ChoreCreate(title="Wipe the table"))
        chore_id = created["chores"][-1]["id"]
        with self.assertRaises(HTTPException) as cross_house_update:
            main.update_chore(other["id"], chore_id, main.ChoreUpdate(completed=True))
        self.assertEqual(cross_house_update.exception.status_code, 404)
        self.assertEqual(main.get_household(other["id"])["chores"], [])

    def test_household_mutation_responses_keep_notifications_scoped_to_selected_profile(self):
        with main.database() as db:
            for index, member_id in enumerate(self.member_ids[:2]):
                db.execute(
                    """INSERT INTO notifications
                       (id, household_id, title, detail, kind, created_at, recipient_id)
                       VALUES (?, ?, ?, ?, 'note', ?, ?)""",
                    (f"private-notice-{index}", self.household_id, "For one profile", "Demo-only reminder", main.now_iso(), member_id),
                )

        chore_payload = main.create_chore(
            self.household_id,
            main.ChoreCreate(title="Water the fern"),
            member_id=self.member_ids[0],
        )
        chore_notice_ids = {notice["id"] for notice in chore_payload["notifications"]}
        self.assertIn("private-notice-0", chore_notice_ids)
        self.assertNotIn("private-notice-1", chore_notice_ids)

        expense_payload = main.create_expense(
            self.household_id,
            main.ExpenseCreate(
                title="Shared soap", amount="6.00", participant_ids=self.member_ids[:2],
                payer_id=self.member_ids[0],
            ),
            member_id=self.member_ids[1],
        )
        expense_notice_ids = {notice["id"] for notice in expense_payload["notifications"]}
        self.assertIn("private-notice-1", expense_notice_ids)
        self.assertNotIn("private-notice-0", expense_notice_ids)

    def test_equal_split_cent_remainder_and_individual_payment(self):
        result = main.create_expense(self.household_id, main.ExpenseCreate(
            title="Shared kitchen supplies", amount=Decimal("10.00"),
            participant_ids=self.member_ids, payer_id=self.member_ids[0], split_type="equal",
        ))
        expense = next(item for item in result["expenses"] if item["title"] == "Shared kitchen supplies")
        self.assertEqual([share["amount_cents"] for share in expense["shares"]], [334, 333, 333])
        self.assertTrue(expense["shares"][0]["paid"])
        self.assertEqual(expense["outstanding_cents"], 666)
        self.assertEqual(expense["status"], "Partially paid")
        balances = {item["member_id"]: item for item in result["balances"]}
        self.assertEqual(balances[self.member_ids[0]]["owed_cents"], 666)
        self.assertEqual(balances[self.member_ids[1]]["owes_cents"], 333)
        self.assertEqual(sum(item["net_cents"] for item in balances.values()), 0)

        paid = main.mark_expense_share_paid(
            self.household_id, expense["id"], self.member_ids[1],
            main.ExpenseSharePaid(member_id=self.member_ids[1]),
        )
        updated = next(item for item in paid["expenses"] if item["id"] == expense["id"])
        self.assertTrue(next(share for share in updated["shares"] if share["member_id"] == self.member_ids[1])["paid"])
        self.assertEqual(updated["outstanding_cents"], 333)
        self.assertEqual(main.get_household(self.household_id)["expense_totals"]["outstanding_cents"], 333)

        # Repeating the same payment request is idempotent and cannot double-count a share.
        repeated = main.mark_expense_share_paid(
            self.household_id, expense["id"], self.member_ids[1],
            main.ExpenseSharePaid(member_id=self.member_ids[1]),
        )
        self.assertEqual(next(item for item in repeated["expenses"] if item["id"] == expense["id"])["outstanding_cents"], 333)

    def test_custom_split_validation_and_no_partial_database_writes(self):
        created = main.create_expense(self.household_id, main.ExpenseCreate(
            title="Household groceries", amount="42.60", participant_ids=self.member_ids,
            payer_id=self.member_ids[1], split_type="custom", custom_shares=[
                {"member_id": self.member_ids[0], "amount": "10.00"},
                {"member_id": self.member_ids[1], "amount": "12.30"},
                {"member_id": self.member_ids[2], "amount": "20.30"},
            ],
        ))
        expense = next(item for item in created["expenses"] if item["title"] == "Household groceries")
        self.assertEqual([share["amount_cents"] for share in expense["shares"]], [1000, 1230, 2030])
        self.assertEqual(sum(share["amount_cents"] for share in expense["shares"]), 4260)

        before_count = len(main.get_household(self.household_id)["expenses"])
        with self.assertRaises(HTTPException) as mismatch:
            main.create_expense(self.household_id, main.ExpenseCreate(
                title="Bad custom split", amount="10.00", participant_ids=self.member_ids[:2],
                payer_id=self.member_ids[0], split_type="custom", custom_shares=[
                    {"member_id": self.member_ids[0], "amount": "3.00"},
                    {"member_id": self.member_ids[1], "amount": "6.99"},
                ],
            ))
        self.assertEqual(mismatch.exception.status_code, 422)
        self.assertEqual(len(main.get_household(self.household_id)["expenses"]), before_count)

        with self.assertRaises(ValidationError):
            main.ExpenseCreate(title="Too precise", amount="2.001", participant_ids=self.member_ids[:1], payer_id=self.member_ids[0])
        with self.assertRaises(ValidationError):
            main.ExpenseCreate(title="No amount", amount="0", participant_ids=self.member_ids[:1], payer_id=self.member_ids[0])

    def test_payment_is_limited_to_share_owner_and_household(self):
        other = main.create_household(main.HouseholdCreate(name="Elsewhere", members=["Morgan Other"]))
        result = main.create_expense(self.household_id, main.ExpenseCreate(
            title="Laundry soap", amount="9.00", participant_ids=self.member_ids[:2],
            payer_id=self.member_ids[0],
        ))
        expense = next(item for item in result["expenses"] if item["title"] == "Laundry soap")
        with self.assertRaises(HTTPException) as mismatched_identity:
            main.mark_expense_share_paid(
                self.household_id, expense["id"], self.member_ids[1],
                main.ExpenseSharePaid(member_id=self.member_ids[0]),
            )
        self.assertEqual(mismatched_identity.exception.status_code, 403)
        with self.assertRaises(HTTPException) as non_participant:
            main.mark_expense_share_paid(
                self.household_id, expense["id"], self.member_ids[2],
                main.ExpenseSharePaid(member_id=self.member_ids[2]),
            )
        self.assertEqual(non_participant.exception.status_code, 403)
        with self.assertRaises(HTTPException) as foreign_household:
            main.mark_expense_share_paid(
                other["id"], expense["id"], other["members"][0]["id"],
                main.ExpenseSharePaid(member_id=other["members"][0]["id"]),
            )
        self.assertEqual(foreign_household.exception.status_code, 404)

    def test_legacy_demo_expenses_backfill_to_exact_cent_shares(self):
        demo = main.get_household(main.DEMO_ID)
        internet = next(item for item in demo["expenses"] if item["id"] == "bill-1")
        groceries = next(item for item in demo["expenses"] if item["id"] == "bill-2")
        self.assertEqual(internet["amount_cents"], 6800)
        self.assertEqual(sum(share["amount_cents"] for share in internet["shares"]), 6800)
        self.assertEqual(internet["outstanding_cents"], 5100)
        self.assertEqual(groceries["amount_cents"], 4260)
        self.assertEqual(groceries["outstanding_cents"], 0)
        self.assertEqual(groceries["status"], "Settled")


if __name__ == "__main__":
    unittest.main()
