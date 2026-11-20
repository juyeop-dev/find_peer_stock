"""Cross-runtime contract checks; no network, collection, or source writes."""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from history_policy import DEFAULT_POLICY, HistoryPolicyError, load_history_policy, resolve_history_policy


class HistoryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))

    def test_default_retains_existing_collection_start_and_reference_window(self):
        result = load_history_policy(as_of="2026-11-17")
        self.assertEqual(result["collection"], {
            "start_year": 2014, "end_year": 2026, "start_date": "2014-01-01",
            "end_date": "2026-11-17", "price_reference_days": 12,
            "price_reference_start": "2013-12-20",
        })
        # Migrated adapters resolve the contract at runtime; publication remains
        # independently backed by the existing successful deployment receipt.
        from stock_information import financial_start
        self.assertEqual(financial_start("2026-11-17"), result["collection"]["start_date"])
        script = "import {collectionHistory,publishedHistoryStart} from './automation/live-api/src/history-policy.js'; console.log(JSON.stringify({collection:collectionHistory('2026-11-17'),published:publishedHistoryStart('stock_history')}));"
        output = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT,
                                check=True, capture_output=True, text=True, encoding="utf-8")
        actual = json.loads(output.stdout)
        self.assertEqual(actual["collection"], result["collection"])
        self.assertEqual(actual["published"], "2014-01-01")

    def test_collection_goal_does_not_mutate_policy_or_assert_publication(self):
        self.policy["collection"].update(start_year=2013, end_year=2013)
        before = copy.deepcopy(self.policy)
        result = resolve_history_policy(self.policy, as_of="2026-11-17")
        self.assertEqual(result["collection"]["price_reference_start"], "2012-12-20")
        self.assertEqual(result["collection"]["end_date"], "2013-12-31")
        self.assertEqual(self.policy, before)
        self.assertEqual(set(result), {"policy_schema_version", "publication_manifest_version", "as_of", "collection"})

    def test_python_and_javascript_resolve_the_same_windows_and_reject_the_same_errors(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for the shared runtime contract")
        cases = [({}, "2026-11-17", True),
                 ({"start_year": 2013, "end_year": 2013}, "2026-11-17", True),
                 ({"start_year": 2012, "end_year": None}, "2012-02-29", True),
                 ({"start_year": 1, "end_year": 1, "price_reference_days": 0}, "2026-11-17", True),
                 ({"start_year": 2013.0, "end_year": 2013.0}, "2026-11-17", True),
                 ({"start_year": 2027}, "2026-11-17", False),
                 ({"end_year": 2013}, "2026-11-17", False),
                 ({"end_year": 2027}, "2026-11-17", False),
                 ({"start_year": True}, "2026-11-17", False),
                 ({"price_reference_days": -1}, "2026-11-17", False),
                 ({"price_reference_days": 1.5}, "2026-11-17", False),
                 ({"price_reference_days": 10**20}, "2026-11-17", False),
                 ({"start_year": 1}, "2026-11-17", False),
                 ({}, "2026-02-30", False), ({}, "20261117", False)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for changes, as_of, valid in cases:
                policy = copy.deepcopy(self.policy)
                policy["collection"].update(changes)
                with self.subTest(changes=changes, as_of=as_of):
                    path.write_text(json.dumps(policy), encoding="utf-8")
                    command = [str(node), str(ROOT / "scripts/inspect-history-policy.mjs"),
                               "--config", str(path), "--as-of", as_of]
                    output = subprocess.run(command, capture_output=True, text=True, check=False)
                    if valid:
                        self.assertEqual(output.returncode, 0, output.stderr)
                        self.assertEqual(json.loads(output.stdout), resolve_history_policy(policy, as_of=as_of))
                    else:
                        self.assertEqual(output.returncode, 2, output.stdout)
                        self.assertEqual(output.stdout, "")
                        with self.assertRaises(HistoryPolicyError):
                            resolve_history_policy(policy, as_of=as_of)

    def test_unsupported_contract_and_publication_claims_fail_before_any_work(self):
        policies = []
        for path, value in [(('schema_version',), 2), (('publication', 'manifest_version'), 2),
                            (('publication', 'verified_start'), '2013-01-01'),
                            (('collection', 'published_start_year'), 2013)]:
            policy = copy.deepcopy(self.policy)
            parent = policy
            for part in path[:-1]:
                parent = parent[part]
            parent[path[-1]] = value
            policies.append(policy)
        policies.extend([None, [], {}, {**self.policy, 'collection': None}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            for policy in policies:
                with self.subTest(policy=policy):
                    with self.assertRaises(HistoryPolicyError):
                        resolve_history_policy(policy, as_of="2026-11-17")
                    path.write_text(json.dumps(policy), encoding='utf-8')
                    output = subprocess.run([
                        shutil.which('node'), str(ROOT / 'scripts/inspect-history-policy.mjs'),
                        '--config', str(path), '--as-of', '2026-11-17',
                    ], capture_output=True, text=True, check=False)
                    self.assertEqual(output.returncode, 2)
                    self.assertEqual(output.stdout, '')

    def test_invalid_file_does_not_emit_a_successful_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text('{"schema_version":NaN}', encoding="utf-8")
            for command in [[sys.executable, str(ROOT / 'scripts/history_policy.py')],
                            [shutil.which('node'), str(ROOT / 'scripts/inspect-history-policy.mjs')]]:
                output = subprocess.run([*command, '--config', str(path)], capture_output=True, text=True, check=False)
                self.assertEqual(output.returncode, 2)
                self.assertEqual(output.stdout, '')


if __name__ == "__main__":
    unittest.main()
