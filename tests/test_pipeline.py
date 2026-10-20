"""Unit tests for the validation and reconciliation rules.

Run from the project folder:
    python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pipeline  # noqa: E402


def commitments(rows):
    return pipeline.standardize_commitments(pd.DataFrame(rows, columns=["lp_id", "lp_name", "fund", "commitment_usd"]).astype(str))


def admin(rows):
    return pipeline.standardize_admin(pd.DataFrame(rows, columns=["txn_id", "lp_id", "fund", "txn_type", "txn_date", "amount_usd"]).astype(str))


class QualityRuleTests(unittest.TestCase):
    def setUp(self):
        self.c = commitments([["LP001", "A", "Fund I", "1000000"]])

    def rules(self, admin_rows, c=None):
        return {i["rule"] for i in pipeline.run_quality_rules(c if c is not None else self.c, admin(admin_rows))}

    def test_clean_data_has_no_issues(self):
        self.assertEqual(self.rules([["T1", "LP001", "Fund I", "capital_call", "2022-01-10", "100000"]]), set())

    def test_negative_amount_flagged(self):
        self.assertIn("positive_amount", self.rules([["T1", "LP001", "Fund I", "capital_call", "2022-01-10", "-5"]]))

    def test_bad_date_flagged(self):
        self.assertIn("valid_date", self.rules([["T1", "LP001", "Fund I", "capital_call", "2022-13-40", "100"]]))

    def test_unknown_type_flagged(self):
        self.assertIn("valid_type", self.rules([["T1", "LP001", "Fund I", "fee", "2022-01-10", "100"]]))

    def test_orphan_transaction_flagged(self):
        self.assertIn("referential", self.rules([["T1", "LP999", "Fund I", "capital_call", "2022-01-10", "100"]]))

    def test_over_called_flagged(self):
        self.assertIn("over_called", self.rules([["T1", "LP001", "Fund I", "capital_call", "2022-01-10", "2000000"]]))

    def test_duplicate_commitment_flagged(self):
        c = commitments([["LP001", "A", "Fund I", "1000000"], ["LP001", "A", "Fund I", "1000000"]])
        self.assertIn("duplicate", self.rules([], c))

    def test_missing_commitment_flagged(self):
        c = commitments([["LP001", "A", "Fund I", ""]])
        self.assertIn("required_field", self.rules([], c))


class ReconciliationTests(unittest.TestCase):
    def test_mismatch_and_missing_found(self):
        a = admin([["T1", "LP001", "Fund I", "capital_call", "2022-01-10", "100"],
                   ["T2", "LP001", "Fund I", "capital_call", "2022-04-10", "200"]])
        gl = pd.DataFrame({"txn_id": ["T1"], "lp_id": ["LP001"], "fund": ["FUND I"],
                           "txn_date": [pd.Timestamp("2022-01-10")], "txn_type": ["capital_call"],
                           "amount_usd": [150.0]})
        breaks = pipeline.reconcile(a, gl)
        self.assertEqual(set(breaks["break_type"]), {"amount_mismatch", "missing_in_ledger"})

    def test_within_tolerance_is_not_a_break(self):
        a = admin([["T1", "LP001", "Fund I", "capital_call", "2022-01-10", "100.00"]])
        gl = pd.DataFrame({"txn_id": ["T1"], "lp_id": ["LP001"], "fund": ["FUND I"],
                           "txn_date": [pd.Timestamp("2022-01-10")], "txn_type": ["capital_call"],
                           "amount_usd": [100.50]})
        self.assertEqual(len(pipeline.reconcile(a, gl)), 0)


if __name__ == "__main__":
    unittest.main()
