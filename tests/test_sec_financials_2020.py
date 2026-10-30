from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from backfill_sec_financials_2020 import frame_fact


class SecFinancials2020Tests(unittest.TestCase):
    def fact(self, start, end, value):
        return {'start':start,'end':end,'val':value,'cik':320193,'accn':'0000320193-21-000001'}

    def test_real_period_dates_and_units_preserve_zero_and_losses(self):
        row = frame_fact(self.fact('2020-01-01','2020-03-31',-10),False)
        self.assertEqual(row['type'],'quarterly')
        self.assertEqual(row['value'],-10)
        self.assertEqual(row['currency'],'USD')
        self.assertEqual(frame_fact(self.fact('2019-09-29','2020-09-26',0),True)['value'],0)

    def test_ytd_annuals_future_periods_and_nonfinite_values_cannot_be_quarters(self):
        for fact in [self.fact('2020-01-01','2020-06-30',100),self.fact('2020-01-01','2020-12-31',100),
                     self.fact('2021-01-01','2021-03-31',100),self.fact('2020-01-01','2020-03-31',float('nan'))]:
            self.assertIsNone(frame_fact(fact,False))


if __name__=='__main__':unittest.main()
