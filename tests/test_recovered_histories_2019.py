from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from import_recovered_histories_2019 import retain_curve

class RecoveredHistoryTests(unittest.TestCase):
    def test_complete_original_curve_fills_observed_gap_without_mixing_adjustments(self):
        old={'ticker':'A','currency':'TWD','source':'Yahoo','prices':[['2019-09-06',10,10],['2026-10-30',20,20]]}
        fresh={'ticker':'A','currency':'TWD','source':'TradingView','prices':[['2019-09-06',5,5],['2019-09-09',6,6],['2026-10-29',9,9]]}
        value,alternate=retain_curve(old,fresh)
        self.assertFalse(alternate);self.assertEqual(value['prices'],fresh['prices'])
        self.assertEqual(value['prior_snapshots'][0]['prices'],old['prices'])
        self.assertTrue(value['prior_snapshots'][0]['complete_history'])
        with self.assertRaises(ValueError):retain_curve(old,{**fresh,'currency':'USD'})

    def test_a_stale_recovered_curve_cannot_replace_the_recent_primary(self):
        old={'ticker':'A','currency':'CNY','source':'Yahoo','prices':[['2019-04-26',10,10],['2026-10-30',20,20]]}
        fresh={**old,'source':'TradingView','prices':[['2019-04-29',5,5],['2026-10-01',9,9]]}
        value,alternate=retain_curve(old,fresh)
        self.assertTrue(alternate);self.assertEqual(value['prices'],old['prices'])
        self.assertEqual(value['prior_snapshots'][0]['prices'],fresh['prices'])

if __name__=='__main__':unittest.main()
