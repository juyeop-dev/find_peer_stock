from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from package_static_data import package
from prepare_hosting_release import validate_release,cost_status,prepare
from generate_publication_history import from_deployment


class HostingPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); source=self.root/'source'; source.mkdir(); (source/'index.json').write_text('{"price":1.123456789}')
        self.proof=self.root/'proof.json'
        raw=json.dumps({'status':'complete','workflow':{'conclusion':'success'},'api':{'verified':True},'production_checks':{'fixture':{'exit_code':0}},'coverage':{'start':'2014-01-01'},'verified_at':'2026-01-01T00:00:00Z','commit':'a'*40,'publication':{}}).encode()
        self.proof.write_bytes(raw); pub=from_deployment(raw,'fixtures/proof.json')
        self.release=Path(package(source,self.root/'packed',publication=pub)['ready_directory'])

    def test_validates_original_inventory_and_refuses_extras(self):
        result=validate_release(self.release); self.assertTrue(result['integrity_verified']); self.assertEqual(result['source_files'],1)
        (self.release/'secret.env').write_text('private')
        with self.assertRaises(ValueError): validate_release(self.release)

    def test_local_configuration_has_no_function_or_paid_bindings(self):
        report=prepare(self.release,self.root/'prepared','https://example.invalid/data/',build_ui=False,publication_proof=self.proof)
        self.assertFalse(report['deployed']); self.assertFalse(report['cost_checks']['verified'])
        config=json.loads((Path(report['prepared_directory'])/'wrangler.json').read_bytes())
        self.assertNotIn('main',config); self.assertEqual(config['assets']['run_worker_first'],False)
        self.assertEqual(config['assets']['directory'],str(self.release))

    def test_cost_evidence_requires_all_fields_and_fresh_actual_time(self):
        now=datetime.now(timezone.utc)
        row={'schema_version':1,'checked_at':now.isoformat(),'cloudflare_account_id':'a'*32,'github_repository':'owner/repo','evidence_reference':'review record'}
        for key in ['cloudflare_workers_free_verified','cloudflare_existing_paid_products_reviewed','github_public_repository_verified','github_standard_runner_verified','github_artifact_and_cache_costs_reviewed','github_spending_stop_verified']: row[key]=True
        self.assertTrue(cost_status(row,now)['verified'])
        row['checked_at']=(now-timedelta(days=2)).isoformat(); self.assertFalse(cost_status(row,now)['verified'])
        self.assertFalse(cost_status({})['verified'])

    def test_unsafe_output_and_non_https_host_refused(self):
        with self.assertRaises(ValueError): prepare(self.release,self.release/'nested','https://example.invalid',build_ui=False)
        with self.assertRaises(ValueError): prepare(self.release,self.root/'out','http://example.invalid',build_ui=False)

    def test_headers_cannot_drop_cors_or_cache_rules(self):
        (self.release/'_headers').write_text('/*\n  Cache-Control: no-store\n')
        with self.assertRaisesRegex(ValueError,'headers differ'): validate_release(self.release)

    def test_assets_only_free_resources_do_not_require_unrelated_billing_permissions(self):
        row={'schema_version':2,'checked_at':datetime.now(timezone.utc).isoformat(),'cloudflare_account_id':'a'*32,
             'github_repository':'owner/repo','evidence_reference':'verified configuration and public pricing','estimated_additional_monthly_usd':0}
        for key in ['cloudflare_static_assets_only_verified','no_new_paid_subscriptions_verified','github_public_repository_verified',
                    'github_standard_runner_verified','github_pages_artifacts_only_verified','github_cache_within_free_allowance_verified']: row[key]=True
        self.assertTrue(cost_status(row)['verified'])
        row['github_standard_runner_verified']=False; self.assertFalse(cost_status(row)['verified'])
        row['github_standard_runner_verified']=True; row['estimated_additional_monthly_usd']=1
        self.assertFalse(cost_status(row)['verified'])

    def test_changed_or_missing_evidence_cannot_prepare_a_publication(self):
        self.proof.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'metadata differs'):
            prepare(self.release,self.root/'prepared','https://example.invalid',build_ui=False,publication_proof=self.proof)


if __name__=='__main__': unittest.main()
