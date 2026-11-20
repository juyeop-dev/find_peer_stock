import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_publication_history import from_deployment
from history_policy import DEFAULT_POLICY, load_history_policy, resolve_history_policy

ROOT = Path(__file__).resolve().parents[1]
PROOF = "data/information-audit/2014/deployment.json"


class PublicationHistoryTests(unittest.TestCase):
    def test_baseline_manifest_is_reproducible_from_the_actual_successful_receipt(self):
        raw = (ROOT / PROOF).read_bytes()
        expected = json.loads((ROOT / "shared/published-history.json").read_bytes())
        self.assertEqual(from_deployment(raw, PROOF), expected)
        self.assertEqual(expected["kinds"]["stock_history"]["selection_start_year"], 2014)

    def test_partial_failed_or_future_proof_cannot_expand_publication(self):
        original = json.loads((ROOT / PROOF).read_bytes())
        for kind in ["status", "workflow", "api", "check", "future"]:
            value = copy.deepcopy(original)
            if kind == "status": value["status"] = "pending"
            elif kind == "workflow": value["workflow"]["conclusion"] = "failure"
            elif kind == "api": value["api"]["verified"] = False
            elif kind == "check": next(iter(value["production_checks"].values()))["exit_code"] = 1
            else: value["verified_at"] = "2099-01-01T00:00:00Z"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                from_deployment(json.dumps(value).encode(), PROOF)

    def test_an_earlier_collection_policy_does_not_change_the_verified_manifest(self):
        path = ROOT / "shared/published-history.json"
        before = path.read_bytes()
        policy = json.loads(DEFAULT_POLICY.read_bytes())
        policy["collection"]["start_year"] = 2013
        self.assertEqual(resolve_history_policy(policy, as_of="2026-11-18")["collection"]["start_date"], "2013-01-01")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(load_history_policy(as_of="2026-11-18")["collection"]["start_year"], 2014)


if __name__ == "__main__":
    unittest.main()
