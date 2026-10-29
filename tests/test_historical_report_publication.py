import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import archive_paths as archive


class HistoricalPublicationTests(unittest.TestCase):
    def test_lossless_publication_preserves_original_source_and_previous_public_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public = root / 'public/data'
            target = public / 'new-highs/korea/2021-01-04.json'
            target.parent.mkdir(parents=True)
            old = b'{"previous": 123.4567890123}\n'
            target.write_bytes(old)
            source = root / 'source.json'
            value = {'date':'2021-01-04', 'entries':[{'name':'원본', 'price':123.4567890123, 'change':0, 'profit':-7}]}
            raw = json.dumps(value, ensure_ascii=False).encode()
            source.write_bytes(raw)
            with patch.object(archive, '__file__', str(root/'scripts/archive_paths.py')):
                archive.publish_daily_report(target, value, public)
            self.assertFalse(target.exists())
            self.assertEqual(json.loads(gzip.decompress(target.with_suffix('.json.gz').read_bytes())), value)
            self.assertEqual(source.read_bytes(), raw)
            backup = root/'data/tmp_published_report_backup'/f'{hashlib.sha256(old).hexdigest()}.json'
            self.assertEqual(backup.read_bytes(), old)

    def test_recent_endpoints_stay_json_and_paths_cannot_escape_publication_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root/'public/turnover/korea/2026_10/2026-10-29.json'
            value = {'date':'2026-10-29', 'entries':[]}
            archive.publish_daily_report(target, value, root/'public')
            self.assertEqual(json.loads(target.read_bytes()), value)
            self.assertFalse(target.with_suffix('.json.gz').exists())
            with self.assertRaises(ValueError):
                archive.publish_daily_report(root/'outside.json', value, root/'public')


if __name__ == '__main__':
    unittest.main()
