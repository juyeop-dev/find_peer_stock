import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('packer', Path(__file__).resolve().parents[1] / 'scripts/package_static_data.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.publication = {'schema_version': 1, 'revision': 'fixture', 'evidence': {'sha256': 'a'*64, 'verified_at': '2026-01-01T00:00:00Z'}, 'kinds': {}}

    def put(self, name, raw):
        path = self.source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def pack(self, name='out', **kwargs):
        return p.package(self.source, self.root/name, publication=self.publication, **kwargs)

    def entries(self, report):
        folder = Path(report['ready_directory']); manifest = json.loads((folder/'manifest.json').read_bytes())
        return {key: value for shard in manifest['shards'].values() for key, value in json.loads((folder/shard['path']).read_bytes())['entries'].items()}

    def test_deterministic_standard_tar_preserves_gzip(self):
        raw = gzip.compress(b'{"value":123}', mtime=0)
        self.put('new-highs/korea/2014-01-02.json.gz', raw)
        a, b = self.pack(), self.pack('second')
        self.assertEqual(a['revision'], b['revision'])
        entry = next(iter(self.entries(a).values()))
        with tarfile.open(Path(a['ready_directory'])/entry['container']['path']) as archive:
            self.assertEqual(archive.extractfile(entry['entry']).read(), raw)
        self.assertTrue(a['roundtrip_verified'])

    def test_earlier_year_does_not_repack_later_year(self):
        self.put('new-highs/korea/2014-01-02.json.gz', b'old')
        first = self.pack()
        self.put('new-highs/korea/2013-01-02.json.gz', b'earlier')
        second = self.pack('second')
        name = 'new-highs/korea/2014-01-02.json.gz'
        self.assertEqual(self.entries(first)[name], self.entries(second)[name])

    def test_numeric_listing_is_not_a_calendar_year(self):
        self.assertEqual(p.group_key('stock-history/2014.T.json.gz')[2], p.digest(b'stock-history/2014.T.json.gz')[:2])

    def test_large_files_direct_and_segmented(self):
        self.put('credit/index.json', b'a'*40000)
        self.put('investors/index.json.gz', b'b'*150000)
        result = self.pack(bundle_bytes=16384, direct_threshold=32000, max_asset_bytes=65536)
        entries = self.entries(result)
        self.assertEqual(entries['credit/index.json']['format'], 'raw-v1')
        self.assertEqual(entries['investors/index.json.gz']['format'], 'segments-v1')
        self.assertLessEqual(result['largest_asset_bytes'], 65536)

    def test_limit_failure_preserves_active(self):
        self.put('index.json', b'old')
        self.pack(); old = (self.root/'out/active.json').read_bytes()
        self.put('credit/index.json', b'new')
        with self.assertRaisesRegex(ValueError, 'limits exceeded'):
            self.pack(max_files=1)
        self.assertEqual((self.root/'out/active.json').read_bytes(), old)

    def test_corrupted_immutable_release_rejected(self):
        self.put('index.json', b'original')
        report = self.pack(); entry = next(iter(self.entries(report).values()))
        (Path(report['ready_directory'])/entry['container']['path']).write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'immutable release differs'):
            self.pack()

    def test_previous_version_kept(self):
        self.put('index.json', b'old')
        first = self.pack()
        self.put('index.json', b'new')
        second = self.pack(previous=Path(first['ready_directory']))
        old_entry = self.entries(first)['index.json']
        self.assertTrue((Path(second['ready_directory'])/old_entry['container']['path']).is_file())
        manifest = json.loads((Path(second['ready_directory'])/'manifest.json').read_bytes())
        self.assertEqual(json.loads((Path(second['ready_directory'])/manifest['previous']['path']).read_bytes())['revision'], first['revision'])

    def test_publication_count_cannot_use_older_source(self):
        self.put('stock-history/a.json.gz', b'a')
        self.publication['kinds']['stock_history'] = {'selection_start_year':2014, 'selection_end_year':2025, 'scope':'observed_with_listing_exceptions', 'published_items':2}
        with self.assertRaisesRegex(ValueError, 'missing verified'):
            self.pack()

    def test_future_or_inverted_evidence_rejected(self):
        self.put('index.json', b'a')
        self.publication['evidence']['verified_at'] = '2099-01-01T00:00:00Z'
        with self.assertRaises(ValueError): self.pack()

    def test_paths_and_source_overlap_rejected(self):
        for name in ['../secret.json', '/secret.json', 'credit/a?x.json', 'credit/a%2f.json', 'a\\b.json']:
            self.assertFalse(p.valid_path(name))
        self.put('private/token.json', b'a')
        with self.assertRaisesRegex(ValueError, 'approved public-data'): self.pack()
        with self.assertRaisesRegex(ValueError, 'non-overlapping'):
            p.package(self.source, self.source/'out', publication=self.publication)


if __name__ == '__main__': unittest.main()
