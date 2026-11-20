import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_static_ci import extract_compatibility, prepare_publication


class StaticPublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def compatibility_archive(self, entries):
        archive = self.root / 'compatibility.zip'
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as tar:
            for name, raw in entries:
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                tar.addfile(item, io.BytesIO(raw))
        with ZipFile(archive, 'w') as zipped:
            zipped.writestr('artifact.tar', data.getvalue())
        return archive

    def test_keeps_legacy_data_and_assets_in_the_new_pages_artifact(self):
        archive = self.compatibility_archive([
            ('./data/index.json', b'{"generated_at":"original"}'),
            ('./assets/old.js', b'// old browser bundle'),
            ('./index.html', b'previous UI'),
        ])
        dest = self.root / 'legacy'
        extract_compatibility(archive, dest)
        self.assertEqual((dest / 'data/index.json').read_bytes(), b'{"generated_at":"original"}')
        self.assertEqual((dest / 'assets/old.js').read_bytes(), b'// old browser bundle')
        self.assertFalse((dest / 'index.html').exists())

    def test_checks_the_frozen_archive_paths_before_writing_any_outside_destination(self):
        archive = self.compatibility_archive([('./data/../../escaped', b'invalid')])
        with self.assertRaisesRegex(ValueError, 'Unsafe or duplicate'):
            extract_compatibility(archive, self.root / 'legacy')
        self.assertFalse((self.root / 'escaped').exists())

    def test_data_only_refresh_keeps_existing_revision_if_the_published_bytes_match(self):
        previous = self.root / 'previous'
        candidate = self.root / 'candidate'
        for directory in [previous, candidate]:
            directory.mkdir()
        common = {'source_inventory_sha256': 'same inventory', 'publication': {'year': 2014}}
        (previous / 'manifest.json').write_text(json.dumps({**common, 'revision': 'old'}))
        (candidate / 'manifest.json').write_text(json.dumps({**common, 'revision': 'new'}))
        report = {'data': {'revision': 'old'}, 'prepared_directory': str(self.root / 'prepared'),
                  'cost_checks': {'verified': True}}
        environment = {'GITHUB_REPOSITORY': 'owner/repo', 'CLOUDFLARE_ACCOUNT_ID': 'a' * 32, 'GH_TOKEN': 'fixture'}
        with patch.dict('os.environ', environment), \
             patch('prepare_static_ci.github_cost_evidence', return_value={}), \
             patch('prepare_static_ci.download', return_value={'directory': str(previous)}), \
             patch('prepare_static_ci.package', return_value={'ready_directory': str(candidate)}), \
             patch('prepare_static_ci.prepare', return_value=report) as prepare, \
             patch('prepare_static_ci.download_compatibility') as compatibility:
            result = prepare_publication(self.root / 'source', self.root / 'out', 'https://example.com/', pages=False)
        self.assertEqual(result['revision'], 'old')
        self.assertFalse(result['changed'])
        self.assertEqual(result['pages'], '')
        self.assertEqual(prepare.call_args.args[0], previous)
        compatibility.assert_not_called()


if __name__ == '__main__':
    unittest.main()
