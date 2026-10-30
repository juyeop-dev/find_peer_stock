from datetime import date
from pathlib import Path
import sys,unittest,tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import dated_fx
from backfill_yahoo_calendars import Bar

class DatedFxTests(unittest.TestCase):
    def test_ecb_cross_uses_the_same_day_and_keeps_missing_days_missing(self):
        day=date(2019,5,22)
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder);path=cache/'official-fx/ecb-eurofxref-hist.xml';path.parent.mkdir()
            path.write_text('<Envelope><Cube><Cube time="2019-05-22"><Cube currency="USD" rate="1.12"/><Cube currency="DKK" rate="7.46"/></Cube></Cube></Envelope>')
            values,source=dated_fx.ecb_usd_rates('DKK',{day,date(2019,5,23)},cache)
        self.assertEqual(values,{day:1.12/7.46})
        self.assertEqual(source['observations'],{'2019-05-22':{'USD_per_EUR':1.12,'DKK_per_EUR':7.46}})

    def test_missing_forward_quote_uses_only_an_actual_same_day_inverse_quote(self):
        first,second=date(2019,5,21),date(2019,5,22)
        def request(symbol,**kwargs):
            return {'chart':{'result':[{'meta':{'symbol':symbol,'currency':'USD' if symbol=='CADUSD=X' else 'CAD','exchangeTimezoneName':'UTC'}}]}}
        def bars(payload,symbol,zone):
            day,value=(first,.74) if symbol=='CADUSD=X' else (second,1.35)
            return [Bar(day,value,value,value,value,0)]
        with patch.object(dated_fx,'request_yahoo',side_effect=request),patch.object(dated_fx,'parse_bars',side_effect=bars):
            values,source=dated_fx.usd_rates_for_dates('CAD',{first,second},Path('unused'))
        self.assertEqual(values,{first:.74,second:1/1.35})
        self.assertTrue(source['sources'][1]['inverted'])
        self.assertEqual(source['sources'][1]['usd_per_currency_by_date'],{'2019-05-22':1/1.35})

    def test_absent_date_or_wrong_pair_currency_cannot_be_published(self):
        day=date(2019,5,22)
        def payload(symbol,**kwargs):return {'chart':{'result':[{'meta':{'symbol':symbol,'currency':'USD' if symbol=='CADUSD=X' else 'CAD','exchangeTimezoneName':'UTC'}}]}}
        with patch.object(dated_fx,'request_yahoo',side_effect=payload),patch.object(dated_fx,'parse_bars',return_value=[]),patch.object(dated_fx,'official_usd_rates',return_value=({},{})):
            with self.assertRaisesRegex(ValueError,'missing exact-date'):dated_fx.usd_rates_for_dates('CAD',{day},Path('unused'))
        with patch.object(dated_fx,'request_yahoo',return_value={'chart':{'result':[{'meta':{'symbol':'CADUSD=X','currency':'CAD'}}]}}):
            with self.assertRaisesRegex(ValueError,'identity/unit'):dated_fx.usd_rates_for_dates('CAD',{day},Path('unused'))

if __name__=='__main__':unittest.main()
