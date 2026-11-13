"""Check every primary curve instead of requiring another year's repair receipt."""
from datetime import datetime, timezone
import gzip
import json

from stock_chart_history import ROOT, PACKS, write_json


def main():
    checked=points=0
    coarse=[]
    for path in sorted(PACKS.glob("*.json.gz")):
        for ticker,value in json.loads(gzip.decompress(path.read_bytes())).items():
            prices=value.get("prices",[])
            checked+=1
            points+=len(prices)
            if len(prices)>=12 and sum(point[0][8:]=="01" for point in prices)>=len(prices)*.8:
                coarse.append({"ticker":ticker,"source":value["source"],"points":len(prices)})
    result={"checked_at":datetime.now(timezone.utc).isoformat(),"primary_curves":checked,"primary_price_points":points,
        "remaining_monthly":len(coarse),"coarse_primary_curves":coarse,
        "parser_policy":"Yahoo responses declaring non-daily granularity or duplicate dates are rejected before storage"}
    write_json(ROOT/"data/information-audit/2015/daily-frequency-audit.json",result)
    assert checked>24000 and not coarse,result
    print(f"Daily frequency verified: {checked} primary curves, {points} observations, no monthly/quarterly primary curves",flush=True)


if __name__=="__main__":
    main()
