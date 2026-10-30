from pathlib import Path
import json
import sqlite3
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import stock_chart_history as charts


class ExtensionPriorityTests(unittest.TestCase):
    def values(self):
        old={'ticker':'TEST','currency':'USD','source':'Previous verified curve','fetched_at':'2026-10-29T12:00:00Z','prices':[['2020-12-21',1,1],['2026-10-29',2,2]]}
        fresh={'ticker':'TEST','currency':'USD','source':'Original dated curve','fetched_at':'2026-10-30T00:00:00Z','requested_range':'10y','prices':[['2019-12-20',1,1],['2026-10-28',3,3]]}
        return old,fresh

    def database(self,old):
        db=sqlite3.connect(':memory:');db.execute('CREATE TABLE history(ticker TEXT PRIMARY KEY,value TEXT)');db.execute('INSERT INTO history VALUES (?,?)',('TEST',json.dumps(old)));return db

    def test_explicit_extension_retains_original_points_in_separate_snapshot(self):
        old,fresh=self.values();db=self.database(old)
        charts.save_candidate(db,fresh,historical_start='2020-01-01')
        value=json.loads(db.execute('SELECT value FROM history').fetchone()[0])
        self.assertEqual(value['prices'],fresh['prices'])
        self.assertEqual(value['prior_snapshots'][0]['prices'],old['prices'])
        db.close()

    def test_dated_request_can_fill_the_earlier_period(self):
        old,fresh=self.values();fresh.update(requested_range='dated',requested_start='2019-12-20');db=self.database(old)
        charts.save_candidate(db,fresh,historical_start='2020-01-01')
        self.assertEqual(json.loads(db.execute('SELECT value FROM history').fetchone()[0])['prices'][0][0],'2019-12-20')
        db.close()

    def test_default_refresh_and_a_stale_or_other_currency_extension_preserve_current_curve(self):
        old,fresh=self.values()
        for mode in ['default','stale','currency']:
            candidate=json.loads(json.dumps(fresh));db=self.database(old)
            if mode=='stale':candidate['prices'][-1][0]='2026-10-01'
            if mode=='currency':candidate['currency']='EUR'
            charts.save_candidate(db,candidate,**({} if mode=='default' else {'historical_start':'2020-01-01'}))
            self.assertEqual(json.loads(db.execute('SELECT value FROM history').fetchone()[0]),old)
            db.close()


if __name__=='__main__':unittest.main()
