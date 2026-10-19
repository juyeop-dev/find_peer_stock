# Stock Peer Site

신고가·거래대금 캘린더와 누적 기록의 종목명을 선택하면 내부 종목 상세 화면으로 이동합니다. 반도체 목록의 종목은 `/semiconductors/{ticker}`의 기존 주가·투자 지표·확정 실적 화면을 재사용합니다. 그 외 종목은 `/market-stocks/{ticker}`에서 선택한 날짜의 기본 정보, 캘린더 등장일의 종가 차트·표, TradingView의 실적 위젯과 선택적 전체 일봉 차트를 표시합니다. `generate_calendar_stock_data.py`가 모든 캘린더 원본에서 시장·티커별 가격 기록을 만들며 개발·빌드에 자동으로 포함됩니다. 등장일 가격은 연속 일봉이나 조정 종가가 아니며 서로 다른 통화를 섞지 않습니다. 거래소별 종목 코드를 유지하고, 외부 자료 수신 실패 시 재시도와 외부 시세 링크를 제공합니다. `캘린더로 돌아가기`는 원래 시장·날짜·거래소 조건을 보존합니다. 위젯은 제공처의 지원 범위에 따라 일부 종목의 자료가 없을 수 있습니다.

종목 연결 검증: 프런트엔드에서 `npm run test:stock-details`, `npm run build` 후 `npm run test:stock-details:browser`.

`캘린더 누적 기록` 페이지(`/calendar-history`)에서 시장별 신고가·거래대금 기록을 월별 또는 연도별로 조회합니다. 기록일 수, 신고가 유형별 누적 건수, 거래대금 TOP 30의 통화별 누적 거래대금, 고유 종목 수와 종목별 등장일 수를 표시하며 날짜를 선택하면 기존 일별 리포트로 이동합니다. 미등록 날짜는 0건으로 간주하지 않습니다.

두 캘린더의 기존 데이터 생성 명령은 `history/{market}/{year}.json` 연간 파일도 함께 생성합니다. 이 파일에는 월별 종목 집계가 들어 있어 연간 조회에도 일별 리포트 전체를 내려받지 않습니다. 기존 예약 갱신과 빌드 과정에 자동으로 포함됩니다.

검증: `python -m unittest discover -s tests -p 'test_calendar_history.py'`, 프런트엔드에서 `npm run test:calendar-history`, `npm run build` 후 `npm run test:calendar-history:browser`.

## 국내 반도체 섹터

- `/semiconductors`: 이미지에 실린 65개 기업을 포함한 코스피·코스닥 반도체 관련 96개 종목을 대분류/중분류/소분류, 시장, 날짜로 탐색합니다.
- `/semiconductors/trends`: 분류별 7/30/90/180/360일 수익률과 동일 비중 주가 추이, 구성 종목의 수익률을 표시합니다.
- `/semiconductors/{ticker}`: 종목별 일봉 차트, 현재가, 시가총액·PER·PBR·52주 범위, 연간·분기 확정 실적을 표시합니다.
- `/credit-balance`: 금융투자협회 신용거래융자 잔고의 전체·코스피·코스닥별 일별 추이와 최근 수치를 표시합니다.

종목과 코드는 `data/seed/semiconductor_stocks.json`, 이미지의 6개 대분류·19개 소분류와 추가 사업 분류 3개는 `data/seed/semiconductor_categories.json`에서 관리합니다. 이미지에 나온 기업은 `image`, 추가한 기업은 `additional`에 기록합니다. 삼성전자처럼 여러 분야에 속한 종목은 각 분야에 표시하며, 상위 단계 섹터 수익률에는 종목당 한 번만 포함합니다. 모든 상장사를 자동 포괄하는 업종 지수는 아닙니다. 일별 종가·조정 종가는 Yahoo Finance, 현재가는 Naver Finance, 확정 매출·영업이익·당기순이익은 Naver Finance 공개 자료를 사용합니다. 재무 수치 단위는 억원이고 추정치(`isConsensus=Y`)는 제외합니다. 종목 수익률은 조정 종가 기준이며 섹터 수익률은 계산 가능한 구성 종목의 수익률을 동일 비중 평균합니다. 차트의 섹터 기준값은 100입니다.

2026-10-14 확장은 배포된 한국 신고가 기록 2026-09-14~2026-10-13(18개 거래일)을 기업 공식 사업 자료와 대조했습니다. 피에스케이홀딩스·메가터치·타이거일렉·뉴파워프라즈마·아이앤씨·케이씨·아스플로·제너셈·샘씨엔에스·디케이락·한국알콜·유니퀘스트·드림텍·비아트론 14개를 추가했습니다. 피에스케이홀딩스는 피에스케이와 별도로 후공정 장비/HBM/첨단패키징에 포함합니다. 유니퀘스트의 유통, 드림텍의 메모리 모듈, 비아트론의 장비 개발은 추가 소분류로 구분하며, 상세 화면에 사업 내용과 출처를 표시합니다. 한국알콜의 자회사·관계기업 연결과 비아트론의 사업화 추진 단계도 명시합니다. 검토한 신고가 날짜·분류·사업 출처는 `data/semiconductor/reviews/2026-10-14.json`에 보관합니다.

`data/semiconductor/index.json`에 가격 이력과 실적을 보존합니다. GitHub Actions는 한국 시장 마감 후 하루 한 번 이 파일을 갱신해 커밋하며, 페이지 빌드 때마다 현재가를 `frontend/public/data/semiconductor/index.json`에 갱신합니다. Yahoo Finance 일봉에서 빠진 최근 거래일은 Naver Finance 일별 시세로 보완합니다. 로컬에서 수동 갱신할 때:

```powershell
python scripts/generate_semiconductor_data.py full --force
python scripts/generate_semiconductor_data.py publish
```

신용 잔고는 금융투자협회 FreeSIS의 신용거래융자 잔고(백만원)를 사용합니다. 코스피·코스닥의 합계와 각 시장값을 `data/credit/index.json` 및 `frontend/public/data/credit/index.json`에 보존합니다. 신용거래대주·예탁증권담보융자·미수금은 포함하지 않으며, 제공처 발표 시차를 따라 최신 기준일을 화면에 표시합니다. 예약 빌드에서 갱신하고, 수동 갱신 명령은 `python scripts/generate_credit_data.py`입니다.

반도체 종목 목록·섹터 구성 종목·종목 상세에는 최근 1년 매출·영업이익과 적용 기간을 표시합니다. 기본 기준은 TTM(최신 발표 분기까지 최근 4개 분기 개별 실적의 합계)이며, 현재 2026년 2Q까지 발표된 종목은 2025년 3Q~2026년 2Q를 합산합니다. 네이버 분기 자료의 추정치(`isConsensus=Y`)는 제외하고, 회사별 최신 발표 분기가 바뀌면 합산 기간도 바뀝니다. 연속 4개 분기가 부족하면 최근 결산 연간 실적을 사용하고 `결산 연간 · 대체`로 명시합니다. 지표 누락을 0으로 처리하거나 매출과 영업이익에 서로 다른 기간을 적용하지 않습니다. 계산 기준·포함 분기·금액은 각 종목의 `recent_financials`에 기록하며, 목록의 실적 값은 가격 선택 날짜와 관계없이 최신 발표 기준입니다.

특정 종목과 peer 기업들의 주가 정보를 비교해서 보는 정적 웹 사이트입니다.

`신고가 캘린더` 페이지(`/new-highs`)에서는 달력 날짜별 신고가 종목, 업종·세부 업종, 해당 거래일 종가와 등락률을 확인합니다. 등록된 국내 peer 기업도 종목 아래에 표시합니다. 검증된 별도 상승 배경이 있을 때만 함께 표시합니다. 한국은 코스피·코스닥 전체를 기본으로 표시하며 거래소별로 좁혀 볼 수 있습니다. 52주 신고가와 역대 신고가를 별도로 집계합니다. 신고가는 장 마감 후 거래일당 한 번 자동 수집하고 날짜별로 보관합니다. 자료 미확인, 신고가 0건, 휴장일을 구분합니다.

`거래대금 캘린더` 페이지(`/turnover`)에서는 시장별·거래일별 거래대금 상위 30개 종목을 순위, 당일 종가, 등락률, 거래대금, 시가총액, 산업과 함께 표로 확인합니다. TradingView 로고 식별자가 있는 종목은 기업 로고를 표시하고, 로고가 없거나 로딩에 실패하면 종목명 이니셜을 표시합니다. 원본은 `data/turnover/reports/{시장}/{YYYY_MM}/{YYYY-MM-DD}.json`에 보존합니다. 게시 파일과 프런트엔드 경로도 `data/turnover/{시장}/{YYYY_MM}/{YYYY-MM-DD}.json`을 사용합니다.

두 캘린더의 평일 휴장은 `data/market-closures/{연도}.json`에 공식 거래소 일정과 출처를 기록해 다음 거래일 전에 표시합니다. 새 연도 일정은 해당 연도 파일로 추가하며, 유럽 묶음은 4개 거래소가 모두 닫는 날만 전체 휴장으로 표시합니다. 등록된 거래일 리포트는 휴장 일정과 충돌하더라도 우선합니다. 공식 일정에 없는 지난 휴장은 신고가 원본의 전후 거래일 증거로 확인된 경우에만 추가 표시됩니다.

신고가 peer 목록은 `data/new-highs/peer-map.json`에 보관합니다. `company_info/peer_map.json`을 수정한 뒤 로컬에서 `python .\scripts\sync_new_high_peers.py`를 실행해 사이트용 목록을 갱신합니다. 날짜별 리포트에 직접 입력한 `peers`가 있으면 그 목록을 우선 사용합니다.

신고가와 거래대금 종목은 선택적으로 `period_returns`를 가질 수 있습니다. 예: `"period_returns": {"1w": {"change_pct": 4.5, "start_date": "2026-09-25", "end_date": "2026-10-02", "basis": "close_to_close"}}`. 월간은 `1m` 키를 사용합니다. 각 값은 해당 리포트 날짜의 종가와 기준 거래일의 종가를 비교한 수익률이며, 기준일과 종료일을 함께 기록해야 합니다. 주간 기준일은 종료일 7일 전, 월간 기준일은 종료일의 전월 같은 날짜를 기준으로 가장 가까운 이전 거래일을 사용합니다. 값이 없는 기간은 표시하지 않습니다. 기존 `change_pct`는 당일 등락률로 유지합니다.

```powershell
python .\scripts\refresh_turnover.py
python .\scripts\generate_turnover_data.py
```

1차 MVP는 FastAPI 없이 동작합니다.

- 외부 Cloudflare 예약 실행이 5분마다 GitHub Actions를 호출하고, 모든 ticker의 가격 JSON을 새로 조회합니다. 외부 예약 실행은 별도 계정·토큰을 등록하고 배포해야 활성화됩니다.
- 기존 GitHub Actions 예약 실행도 예비 수단으로 유지합니다. 예약식이 5분이어도 실제 실행 간격은 길어질 수 있습니다.
- React 프론트엔드는 `public/data/*.json`을 읽어서 화면을 그립니다.
- 메인·종목 상세·신고가 페이지는 1분마다 캐시 없이 JSON을 확인합니다. 다른 탭에서 돌아오거나 연결이 복구되면 바로 다시 확인합니다.
- 신고가 캘린더는 시장·거래소를 바꿔도 최신 거래일을 자동으로 따라갑니다. 달력에서 날짜를 직접 고르면 해당 날짜를 유지하며, `최신 기록 자동 보기`로 자동 이동을 다시 켭니다.
- 주말은 달력에 바로 휴장으로 표시합니다. 평일 휴장은 다음 정상 거래일 자료의 직전 거래일을 대조해 확정하며, 여러 거래소를 묶은 시장은 모든 거래소가 쉬었을 때만 시장 휴장으로 표시합니다. 단순한 미수집 날짜는 휴장으로 추정하지 않습니다.
- 조회 실패 시 마지막 정상 가격과 원래 조회 시각을 보존하며, 화면에 이전 가격임을 표시합니다. 모든 시세 조회가 실패하면 기존 가격 파일과 시각을 유지하며 일별 신고가 게시를 계속합니다.
- 나중에 FastAPI를 붙일 수 있도록 JSON 응답 구조를 API 응답처럼 유지합니다.

## 로컬 데이터 생성

기존 가격을 유지하면서 구조만 다시 생성하려면:

```powershell
python .\scripts\generate_static_data.py --no-fetch
```

실제 시세 조회까지 시도하려면 `--no-fetch`를 빼고 실행합니다. 기본 실행은 국가별 장 시간과 무관하게 모든 ticker를 조회합니다.

```powershell
python .\scripts\generate_static_data.py
```

생성 결과:

```text
data/generated/
frontend/public/data/
```

예약 실행에서 생성한 가격 데이터는 GitHub Pages artifact에만 포함하며 `main`에 반복 커밋하지 않습니다. 기능 변경을 커밋할 때도 `data/generated`와 `frontend/public/data`의 변동성 높은 가격 스냅샷은 가급적 제외하고, 로컬 확인이 필요할 때만 위 수집 명령으로 갱신합니다. 이 방식은 5분 단위 자동 시세 커밋과 개발 커밋 사이의 반복적인 merge conflict를 막습니다. `npm run dev`만 실행하면 시세 수집은 시작되지 않습니다.

`generated_at`은 파일 생성 시각, `quote.fetched_at`은 마지막 성공한 가격 조회 시각, `quote.market_time`은 제공처가 알려 준 시세 기준 시각입니다. 재조회 실패 시 `status: "stale"`, `refresh_status: "error"`, `last_checked_at`으로 실패 상태와 시도를 기록합니다. 주말이나 휴장에는 이전 거래일 가격이 유지되는 것이 정상입니다. 화면의 `브라우저 확인`은 배포 파일을 읽은 시각이며 가격이 갱신됐다는 뜻은 아닙니다.

배포된 사이트의 갱신 상태는 인증정보 없이 확인할 수 있습니다.

```powershell
python .\scripts\check_refresh_status.py
```

데이터 생성 시각과 경과 시간을 JSON으로 출력합니다. 기본 20분 이내면 종료 코드 `0`, 20분 초과나 조회 오류면 `1`입니다. `--max-age-minutes 10`으로 기준을 바꾸거나 `--site-url`로 다른 배포 주소를 지정할 수 있습니다. 이 명령은 배포 파일의 나이를 확인하며, 시세를 수집하거나 로컬 파일을 갱신하지 않습니다. 장외 가격이 그대로인지는 종목의 `quote.market_time`과 함께 확인합니다.

## 일별 신고가 자료 추가

자동 수집부터 화면 반영까지의 경로는 `data/new-highs/reports/{시장}/{날짜}.json`(보존 원본) → `data/generated/new-highs`(검증된 게시 자료 및 달력 목록) → `frontend/public/data/new-highs`(사이트 배포 파일)입니다. 국가·날짜별 구조가 같은 것은 의도된 복사이며, 수동 보완은 원본에만 합니다. 게시 폴더는 자동 생성되므로 직접 수정하지 않습니다.

신고가 원본은 시세 JSON과 별도로 누적합니다. 아래 경로에 시장별·날짜별 JSON 파일을 추가하면 됩니다. `date`는 해당 시장의 거래일이며 파일명과 일치해야 합니다.

한국 신고가의 종목명은 네이버의 종목코드별 표시 명칭을 사용합니다. 수집 후보는 해당 거래일의 일봉 고가·거래량과 이전 52주 일봉으로 추가 대조하며, 일봉으로 반박되는 후보는 제외하고 자료를 읽지 못하면 재시도합니다. 기존 한국 원본의 이름만 보완하려면 `python scripts/localize_korean_new_highs.py`를 실행한 뒤 게시 자료를 생성합니다. 이 명령은 과거 가격·분류·수집 시각을 바꾸지 않습니다. 날짜별 검토 근거는 `data/new-highs/reviews`에 보관합니다.

```text
data/new-highs/
  markets.json
  reports/
    korea/
      YYYY-MM-DD.json
    us/
      YYYY-MM-DD.json
```

아래는 **작성 양식**이며 실제 종목·날짜·사유로 교체해야 합니다. 예시 기업이나 수치를 실제 리포트로 등록하지 않습니다.

```json
{
  "schema_version": 1,
  "market": "korea",
  "date": "YYYY-MM-DD",
  "summary": "해당 거래일 신고가 흐름 요약",
  "sources": [{ "label": "확인한 원문 자료", "url": "https://example.com/source" }],
  "category_reasons": {
    "업종 또는 테마": "이 업종·테마 종목의 공통 신고가 사유"
  },
  "entries": [
    {
      "ticker": "실제종목코드.KS",
      "name": "기업명",
      "exchange": "KOSPI",
      "category": "업종 또는 테마",
      "high_type": "52_week",
      "reason": "업종: 정보기술 · 반도체 장비",
      "description": "기업의 주요 사업 또는 세부 업종 설명",
      "change_pct": 3.25,
      "session_open": 10000,
      "session_close": 10500,
      "currency": "KRW"
    }
  ]
}
```

- `high_type`은 `52_week`(52주 신고가) 또는 `all_time`(역대 신고가)입니다. 두 조건에 모두 해당하면 **`all_time`으로 한 번만 등록**합니다. 따라서 52주 신고가 집계에는 역대 신고가를 중복 포함하지 않습니다.
- `ticker`, `name`, `exchange`, `category`, `high_type`, `reason`은 필수입니다. 같은 날짜·시장의 동일 ticker 중복을 허용하지 않습니다. 한국 티커는 코스피 `.KS`, 코스닥 `.KQ` 표기를 권장합니다.
- `category`로 예전 자료처럼 업종·테마를 묶습니다. 선택 항목인 `category_reasons`에 공통 사유를 쓰고, `reason`에는 개별 기업 사유를 씁니다. 공통 사유만 있는 종목은 같은 내용을 `reason`에도 넣습니다. `category_reasons`의 키는 실제 등록 종목의 `category`와 일치해야 합니다.
- `description`은 사업 내용 또는 세부 업종, `reason`은 자동 자료에서는 `업종: 대분류 · 세부 업종`입니다. 검증된 뉴스 등 실제 상승 배경이 있으면 `reason`과 `category_reasons`에 보완할 수 있습니다.
- `session_open`과 `session_close`는 해당 거래일의 시가·종가이며 양수여야 합니다. `currency`는 `KRW`, `JPY`, `USD` 같은 3자리 통화 코드입니다. 이 값들은 이전 자료와의 호환을 위해 선택 항목이지만 자동 자료에는 함께 저장합니다. `change_pct: 3.25`는 3.25%이며, 등락률 미확인 시 생략하거나 `null`로 둡니다.
- `sources`는 원문 자료 이름과 선택적인 HTTP(S) 링크 목록입니다. 링크가 없는 사용자 제공 자료는 `label`만 쓸 수 있습니다.
- 파일이 없는 날짜는 **미등록**입니다. 확인 결과 신고가가 없는 날만 `entries: []`인 파일을 등록합니다. 빈 리포트는 해당 시장에 설정된 모든 거래소의 신고가가 0건인 것으로 표시하므로, 시장 내 거래소 자료를 확인한 뒤 등록합니다.

신고가 자료만 검증·생성하려면 저장소 루트(`stock_peer_site`)에서 실행합니다. 기존 peer 주가 파일을 변경하거나 시세를 조회하지 않습니다.

```powershell
python .\scripts\generate_new_high_data.py
```

모든 원본을 먼저 검증한 뒤 아래 경로에 날짜별 JSON과 달력용 `index.json`을 생성합니다. 원본 리포트를 남겨 두면 이후 실행에서도 이전 날짜 자료가 유지됩니다. 게시 목록은 현재 원본 파일 기준으로 다시 생성됩니다.

```text
data/generated/new-highs/index.json
data/generated/new-highs/{market}/{YYYY-MM-DD}.json
frontend/public/data/new-highs/index.json
frontend/public/data/new-highs/{market}/{YYYY-MM-DD}.json
```

`generate_static_data.py`는 등록된 신고가 원본을 게시 파일로 변환합니다. 자동 수집은 별도 `scripts/refresh_new_highs.py`가 담당합니다. 직접 조사한 사유나 보완 자료는 `data/new-highs/reports` 원본을 수정합니다. 자동 수집은 이미 등록된 날짜를 덮어쓰지 않습니다.

### 장 마감 후 하루 한 번 자동 수집

```powershell
python .\scripts\refresh_new_highs.py
python .\scripts\generate_new_high_data.py
```

한국의 지난 거래일을 다시 채울 때는 네이버 조정 일봉으로 현재 한국 주식 종목군 전체를 대조하는 전용 명령을 사용합니다. 신고가와 거래대금 상위 30개를 함께 계산하며, 기존 원본을 교체하려면 `--force`를 추가합니다. 성공한 종목 이력은 `data/tmp_korean_history`에 캐시합니다.

```powershell
python .\scripts\backfill_korean_new_highs.py --start 2026-09-07 --end 2026-09-10
python .\scripts\generate_new_high_data.py
python .\scripts\generate_turnover_data.py
```

기존 리포트에 당시 종가가 없거나 자동 생성된 신고가 사유가 미확인으로 남아 있으면 다음 명령으로 실제 거래일의 시가·종가와 업종 설명을 보완한 뒤 다시 게시합니다.

```powershell
python .\scripts\enrich_new_high_reports.py
python .\scripts\generate_new_high_data.py
```

일본·미국의 최근 거래일은 TradingView의 날짜별 일봉 필드로 현재 주식 종목군 전체를 대조해 채웁니다. 각 종목의 실제 일봉 날짜를 확인하므로 휴장일은 빈 리포트로 저장하지 않습니다.

```powershell
python .\scripts\backfill_tradingview_new_highs.py --market japan --start 2026-09-07 --end 2026-09-10
python .\scripts\generate_new_high_data.py
```

| 시장 | 수집 시작 (각 시장 현지시간) |
|---|---|
| 한국·일본 | 16:30 이후 |
| 중국(상하이·선전) | 16:00 이후 |
| 대만 | 14:30 이후 |
| 미국 | 17:00 이후 |
| 유럽 | 파리 시간 19:00 이후 |

일반 시세의 5분 갱신과 별개로, 신고가는 해당 거래일 원본이 성공적으로 저장되면 이후 실행에서 재사용합니다. 실패하거나 해당 거래일 자료가 아직 확인되지 않으면 30분 뒤 재시도합니다. 야간·주말·다음 개장 전에는 직전 평일 자료를 보완할 수 있고, 장중에는 진행 중인 일봉을 저장하지 않습니다. 미국·유럽의 서머타임은 IANA 시간대로 반영합니다.

TradingView 스크리너의 주식 전체 목록을 페이지 끝까지 확인해 당일 장중 고가를 52주·역대 고가와 비교합니다. 장중 신고가에 도달했더라도 종가가 시가보다 낮은 음봉이거나 전일 종가보다 낮은 하락 마감이면 제외합니다. 보합봉과 전일 대비 보합 마감은 포함합니다. 상장 첫날처럼 전일 종가가 없는 종목은 시가·종가 조건만 적용합니다. 두 신고가 조건에 모두 해당하면 역대 신고가로 한 번만 집계합니다. 각 거래소의 실제 일봉 날짜와 직전 일봉 날짜를 확인하며, 그 사이의 평일만 확정 휴장일로 게시합니다. 휴장이나 지연 자료를 임의로 당일 자료 또는 0건으로 저장하지 않습니다. 이 방식은 자료원에 등록된 주식 기준이며, ETF 등 다른 상품은 포함하지 않습니다. 스크리너의 최고가 도달(같은 고가 포함) 기준을 사용합니다. [TradingView 신고가 목록](https://www.tradingview.com/markets/stocks-korea/market-movers-52wk-high/)

중국은 TradingView 중국 스크리너가 제공하는 상하이(SSE)·선전(SZSE) A주를 자동 수집합니다. 베이징거래소(BSE)는 같은 자료원에서 종목을 제공하지 않으므로 자동 수집 범위에 포함하지 않습니다. 신고가 및 거래대금 화면의 중국 전체는 이 두 거래소를 뜻합니다.

### 해외 캘린더 과거 구간 복원

일본·중국·미국·대만의 누락된 최근 구간은 TradingView의 현재 주식 종목군과 Yahoo Finance의 날짜별 OHLCV를 결합해 신고가와 거래대금 캘린더를 함께 복원할 수 있습니다. 과거 거래대금은 Yahoo 종가×거래량 추정치로, TradingView의 `Value.Traded`와 값이나 표시 통화가 다를 수 있습니다. 52주 신고가는 분할 조정 일봉, 역대 신고가는 후보 종목의 분할 조정 전체 월봉으로 추가 판정합니다. 유럽은 Yahoo 종목 매핑의 수집 범위와 통화 환산 문제 때문에 이 방식의 복원을 중지했으며, 신고가는 아래의 동일 거래소 TradingView 차트 경로로 복원합니다.

```powershell
python .\scripts\backfill_yahoo_calendars.py --market japan --start 2026-09-01 --end 2026-09-21
python .\scripts\backfill_yahoo_calendars.py --market china --start 2026-09-01 --end 2026-09-21
python .\scripts\backfill_yahoo_calendars.py --market us --start 2026-09-01 --end 2026-09-21
python .\scripts\backfill_yahoo_calendars.py --market taiwan --start 2026-09-01 --end 2026-09-21
python .\scripts\generate_new_high_data.py
python .\scripts\generate_turnover_data.py
```

유럽 신고가 전용 복원 도구는 유로넥스트·Xetra·런던·스위스의 현재 종목군 전체를 스캔하고, 각 종목의 동일 거래소 차트에서 분할 조정 일봉과 전체 월봉을 조회합니다. 심볼·거래소·통화 일치를 확인하며, 거래량 0·음봉·전일 대비 하락 종목을 제외합니다. 요청 날짜 이후의 같은 달 고가는 역대 신고가 판정에 사용하지 않습니다. 기존 기록은 보존하고 누락된 마감 거래일만 추가합니다. 거래소별 휴장은 공식 출처와 함께 `data/new-highs/europe-exchange-closures.json`에 기록합니다. 연결을 재사용하며 접속 제한이 나오면 수집을 중지합니다. 캐시는 `data/tmp_tradingview_chart`에 보존하고, 날짜별 시계열 검증이 모두 완료된 뒤 게시합니다.

```powershell
python -m pip install -r scripts/requirements-chart-history.txt
python .\scripts\backfill_european_new_highs.py --start 2026-08-01 --end 2026-10-14
python .\scripts\backfill_european_new_highs.py --start 2026-01-01 --end 2026-05-31 --daily-bars 650
python .\scripts\generate_new_high_data.py
```

도구는 시장별 장 마감 전 날짜와 휴장일을 게시하지 않으며 기존 원본을 기본적으로 보존합니다. Yahoo 회사명과 TradingView 회사명을 대조하고, 거래가 없었던 종목은 별도로 제외합니다. 활성·매핑 가능 종목 및 거래소별 수집률이 기준보다 낮으면 아무 파일도 저장하지 않습니다. 현재 종목군에서 사라진 과거 상장 종목은 복원 범위에 포함되지 않는다는 한계가 원본 메타데이터에 기록됩니다. 다운로드 캐시는 `data/tmp_calendar_history`에 저장되며 Git에서는 제외됩니다.

유럽 역대 고가 판정은 전체 월봉의 가격만 사용합니다. 과거 월봉의 거래량이 누락되거나 음수이면 `volume_unavailable`로 기록하고 거래량 계산에서 사용하지 않습니다. 일봉의 가격·거래량 검증과 거래대금 순위 계산은 그대로 유지하며, 1~5월의 가격 조정 대조·원본 해시는 `data/new-highs/reviews/europe/2026-01_to_2026-05.json`에 보관합니다.

유럽 화면은 유로넥스트·Xetra·런던·스위스 거래소만 다룹니다. TradingView 유럽 거래대금과 시가총액은 미달러 환산값으로 표시하고, 주가는 종목별 표시 통화를 유지합니다. 수집 범위가 부족하거나 거래량 0 신고가가 포함된 2026년 9월 Yahoo 복원본은 `data/review/europe`에 보관하고 게시 목록에서 제외했습니다. 9월 23일 거래대금은 검증 가능한 전체 순위를 복원할 수 없어 공백으로 남겨 두었습니다.

2026년 1~8월 신고가·거래대금 캘린더는 6개 시장의 거래일 전체를 보완했습니다. 한국 6월 3일 지방선거일·7월 17일 제헌절과 대만 7월 10일 태풍 휴장은 출처와 함께 휴장일로 기록합니다. 한국은 Naver Finance, 일본·중국·대만·미국은 Yahoo Finance의 과거 일봉을 사용합니다. 유럽 170거래일은 검증된 동일 거래소 TradingView 일봉 5,371개 종목의 종가×거래량을 Yahoo Finance의 당일 통화별 환율로 미달러 환산해 순위를 복원했습니다. GBX는 GBP의 1/100로 환산하고, 거래소별 휴장일은 해당 거래소의 순위에서 제외했습니다. 연초 신고가 판정에 필요한 52주 일봉은 `--daily-bars 650`으로 조회 기간을 확장하며, 기간이 부족하면 게시하지 않습니다. 복원 거래대금은 실제 체결 금액 합계와 다를 수 있는 추정치이며, 과거 상장폐지 종목은 현재 종목군에 포함되지 않습니다. 날짜별 수집 범위·환율·원본 해시는 `data/turnover/reviews/europe/2026-01_to_2026-05.json`, `data/turnover/reviews/europe/2026-06_to_2026-07.json`, `data/turnover/reviews/europe/2026-08.json`에 보관합니다.

자동 자료의 업종·세부 업종은 자료원 분류를 사용합니다. 가격 데이터만으로 상승 원인을 추측하지 않고 업종 정보를 기본 설명으로 표시하며, 검증한 뉴스나 실제 상승 배경은 원본 자료에 보완할 수 있습니다. `data/new-highs/refresh-status.json`은 시장별 대상일·성공일·재시도 시각을 기록하며, 화면에는 최근 게시 거래일과 갱신 상태를 표시합니다.

GitHub 워크플로는 신고가 원본과 재시도 상태를 먼저 저장한 뒤 시세 수집·빌드를 진행합니다. 저장 실패 시 게시를 중단하고 다음 실행에서 재시도합니다. 외부 예약 실행이나 자료원의 지연이 있어 정확한 시각의 게시를 보장하지는 않습니다. 브라우저의 1분 확인은 새 일별 자료를 화면에 반영하기 위한 동작입니다.

프론트엔드의 `npm run dev`와 `npm run build`도 시작 전에 신고가 생성기를 실행합니다. 개발 서버 실행 중 원본 자료를 추가했다면 위 Python 명령을 다시 실행합니다. 열린 페이지에는 다음 자동 확인 때 반영됩니다.

시장·거래소는 `data/new-highs/markets.json`에서 관리합니다. 한국(`korea`), 미국(`us`), 중국(`china`), 대만(`taiwan`), 일본(`japan`), 유럽(`europe`)을 미리 설정했습니다. 자료가 없는 시장은 빈 상태로 표시됩니다. 새 시장은 `id`, 표시명 `label`, 유효한 IANA 기준 시간대 `timezone`, 기본 거래소 `default_exchange`, 거래소 목록 `exchanges`를 추가한 뒤 같은 형식으로 리포트를 등록합니다. `default_exchange`에는 등록된 거래소 ID 또는 전체 거래소를 뜻하는 `all`을 지정합니다. 현재 모든 시장은 `all`이 기본값입니다. 유럽 거래소도 필요에 따라 목록을 확장할 수 있습니다.

전체 데이터 검증 테스트:

```powershell
python -m unittest discover -s tests
```

## 프론트엔드 실행

Python 3.10 이상, Node.js와 npm 설치 후:

```powershell
cd frontend
npm install
npm run dev
```

빌드:

```powershell
npm run build
```

빌드 후 실제 Chromium 브라우저로 자동 갱신을 검증합니다. Chrome 또는 Edge가 설치되어 있어야 하며, 다른 경로는 `BROWSER_PATH`로 지정합니다. Windows PowerShell에서 `npm.ps1` 실행이 차단되면 `npm.cmd`를 사용합니다.

```powershell
npm.cmd run test:browser
```

메인·종목 상세·신고가 페이지의 새 데이터 반영, 조회 실패 시 기존 기록 유지, 연결 복구 및 갱신 지연 표시를 확인합니다. 테스트용 데이터와 로컬 서버를 사용합니다.

## 배포

각 페이지의 **새로고침** 버튼은 [원본 조회 API](automation/live-api/README.md)를 통해 Yahoo Finance·Naver Finance·TradingView·금융투자협회에서 자료를 다시 가져와 화면에 즉시 반영합니다. `원본 조회 완료` 시각으로 성공 여부를 확인할 수 있습니다. 제공처에서 일부 항목을 가져오지 못하면 기존 항목을 보존하고 안내합니다. 시세 기준 시각과 조회 완료 시각은 별개이며, 제공처가 지연 시세 또는 최근 공표 자료를 반환할 수 있습니다.

신고가·거래대금 캘린더는 최신 목록을 다시 조회하면서 과거 기록을 유지합니다. 월별·연도별 누적 기록에서는 현재 표시된 종목의 현재가를 별도로 조회합니다. 수동 조회 결과는 현재 브라우저 세션에 반영되며, 과거 원본 파일이나 집계를 변경하지 않습니다. 기존 1분 자동 확인과 예약 배포는 배포된 스냅샷을 확인·갱신하는 경로로 계속 동작합니다.

`.github/workflows/build-site.yml`은 아래 작업을 수행합니다.

1. Python으로 모든 ticker의 가격 JSON 생성
2. React 빌드
3. GitHub Pages artifact 업로드
4. GitHub Pages 배포

### PC와 무관한 5분 예약 실행

[외부 스케줄러 설치 안내](automation/refresh-scheduler/README.md)에 따라 Cloudflare Worker를 배포합니다. Worker가 5분마다 GitHub의 `workflow_dispatch`를 호출하므로 PC가 꺼져 있어도 작동합니다. 진행 중인 작업이 있으면 중복 호출을 건너뜁니다. 시세 조회와 Pages 배포에는 추가 시간이 필요하며, 외부 서비스의 지연까지 제거하는 실시간 보장은 아닙니다.

**비용 없이 운영하는 조건:** Cloudflare는 Workers Free 플랜을 사용합니다. 하루 288회 예약 실행을 무료 한도 내에서 처리하고, 실제 수집·빌드는 현재 공개 GitHub 저장소의 무료 표준 실행기에서 수행합니다. 유료 서버나 데이터베이스는 필요하지 않습니다. 자세한 무료 한도와 계정 확인 방법은 위 설치 안내에 있습니다.

GitHub 자체 예약은 `3,8,13,...,58`분에 실행하는 예비 경로입니다. 2026-09-12 조사 당시 이 설정에도 실제 최근 실행은 약 2~4시간 간격이었습니다. [GitHub 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)도 예약 실행 지연·누락 가능성을 명시합니다. 화면은 배포 데이터가 20분 넘게 갱신되지 않으면 지연 안내를 표시합니다.

수동으로 즉시 갱신하려면 Actions에서 `Build Stock Peer Site`를 `Run workflow`로 실행합니다. `force_fetch` 기본값은 `true`이며 `false`이면 기존 가격을 유지하고 사이트만 다시 만듭니다. 워크플로는 시세 전체 수집 실패 시 기존 가격을 보존하고, 테스트와 빌드 통과 후에 게시합니다. 일별 신고가 원본 저장 실패 시 게시를 중단합니다. 예약 실행의 가격 스냅샷은 저장소가 아닌 Pages artifact에만 게시합니다.

소스 코드를 `main`에 푸시하면 워크플로가 최신 가격 데이터를 새로 생성한 뒤 GitHub Pages를 배포합니다. 따라서 일반적인 기능 변경 커밋에 로컬 생성 가격 파일을 함께 넣을 필요가 없습니다.

GitHub Pages는 repository settings에서 `GitHub Actions` 배포 소스로 설정합니다.

외부 스케줄러 검증:

```powershell
node --test automation/refresh-scheduler/test/*.test.mjs
```
