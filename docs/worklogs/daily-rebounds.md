# 국내 일일 반등 페이지

페이지: `/rebounds` · 주 메뉴 ‘일일 반등’.

- `(종가 / 당일 저가 - 1) * 100`으로 반등률을 계산한다. KOSPI는 당일 시총 5조원 이상·반등 8% 이상, KOSDAQ은 1조원 이상·5% 이상이다. 전일 대비 하락은 제외하고 보합은 포함한다. 표시용 반올림 전 수치로 선별하며 상위 30개 제한을 두지 않는다.
- KOSPI와 KOSDAQ을 나눠 반등률 내림차순으로 표시한다. 반등률·종가·전일 대비 등락률·당일 저가·시총을 확인할 수 있다. 검색과 요청한 메시지 형식의 전체 목록 복사를 지원한다.
- 달력은 실제 저장된 날짜와 건수를 표시한다. 정상 수집 후 0개인 날짜, 미등록 날짜, 공식 휴장일/주말을 구분한다. 종목명은 기존 상세 화면으로 연결하며 원래 거래일과 돌아갈 주소를 유지한다.
- `scripts/rebound_data.py collect`는 기존 TradingView 국내 스크리너를 전체 조회한다. KOSPI/KOSDAQ 보통주만 대상으로 ETF·우선주·KONEX·시장 미확인·다른 날짜 봉은 제외한다. 원화 시총과 가격을 사용한다. 시총/등락률이 없는 종목은 제외 건수를 기록하며, 선별 대상 종목의 저가/종가가 유효하지 않으면 불완전한 결과를 저장하지 않는다.
- 양 시장의 원본 기준일을 대조하고 요청한 마감 일봉 날짜와 일치해야 저장한다. 장중에는 수집하지 않으며, 기존 마감 후 수집 경로에 맞춰 15:50부터 시도한다. 과거 요청 날짜에 현재 스크리너 값을 덮어 쓰지 않는다.
- 원본은 `data/rebounds/reports/korea/YYYY_MM/YYYY-MM-DD.json`, 상태는 `data/rebounds/refresh-status.json`에 저장한다. 같은 날짜는 기본적으로 재수집하지 않는다. 실패하면 기존 성공 기록을 보존한다.
- `scripts/rebound_data.py publish`는 전체 원본 검증 후 `frontend/public/data/rebounds/`에 발행한다. `predev`와 `prebuild`에 연결했고, 기존 GitHub Actions의 장 마감 수집·검증·원본 저장 단계에 추가했다. 별도 유료 서비스나 예약 작업은 만들지 않았다.

최초 실데이터: 2026-11-04, 전체 2,638개 조회, 조건 충족 KOSPI 9개·KOSDAQ 37개. 사용자가 제시한 11월 2일의 종목 목록을 고정 데이터로 사용하지 않았다.

검증:

```text
python -m unittest discover -s tests -p test_rebound_data.py -v
cd frontend
node --test tests/rebounds.test.mjs tests/stock-detail-links.test.mjs
node node_modules/typescript/bin/tsc -b
node tests/rebounds-browser.mjs
```

Python 8개와 프런트엔드 8개 테스트, TypeScript 검사, 공개 데이터 복사 없이 별도 임시 디렉터리로 수행한 Vite production build를 확인했다. 브라우저에서는 실제 저장 데이터, 1440/390/320px 화면, 검색·전체 목록 복사·상세/복귀 연결·0건·미등록·휴장·잘못된 날짜·갱신 실패 시 기존 결과 보존을 검증한다. 캡처는 `data/tmp_rebounds/ui/`에 저장한다.

로컬 변경이며 운영 배포는 수행하지 않았다. 자동 수집 단계는 이 변경을 운영 브랜치에 반영한 이후 기존 예약 빌드에서 실행된다.

## 2026-11-05 과거 데이터 추가

2018-01-02~2026-11-05의 2,169거래일, 조건 충족 종목 16,311건을 저장하고 `frontend/public/data/rebounds/`에 발행했다. 조건을 충족한 종목이 없는 171거래일도 정상 0건 기록으로 보존한다. 과거 복원 2,167일과 기존 11월 4일·새로 수집한 11월 5일의 TradingView 마감 기록 2일을 합친 범위다.

| 연도 | 저장 거래일 | 조건 충족 종목 건수 |
| --- | ---: | ---: |
| 2018 | 244 | 917 |
| 2019 | 246 | 410 |
| 2020 | 248 | 1,275 |
| 2021 | 248 | 1,669 |
| 2022 | 246 | 979 |
| 2023 | 245 | 1,677 |
| 2024 | 244 | 1,958 |
| 2025 | 242 | 2,109 |
| 2026 (~11/05) | 206 | 5,317 |

`scripts/backfill_rebounds.py`는 [FinanceData/marcap](https://github.com/FinanceData/marcap)의 KRX 연도별 Parquet 원본을 읽는다. 2018~2024년은 기존 수집본 `eeed0817d1478597b738a3a6149c170ec7e3f4cb`, 2025~2026년은 `468b948c971b567376d41659e0bffd1ad3d3cd1f` 버전이다. 원본 SHA-256·버전·연도를 검증하며 원화 시총은 같은 행의 종가×상장주식수와 대조한다. 가격은 당시 비조정 저가·종가를 함께 사용한다. 2026년 고정 원본은 11월 3일까지 제공하므로 이후 날짜는 실제 스크리너 수집본으로 보완했다.

당시 KOSPI/KOSDAQ 종목 전체에서 보통주 클래스 코드(마지막 자리 `0`)를 선별해 현재 상장 목록에 없는 과거 종목도 포함한다. 우선주·KONEX·거래량 0 종목은 제외한다. 과거 업종을 현재 분류로 대체하지 않고 미분류로 둔다. 양 시장과 최소 1,500개 보통주가 확인되어야 날짜를 인정하며 선별 대상의 저가가 유효하지 않거나 시총 단위가 틀리면 저장하지 않는다. 전체 요청 범위를 검증한 후 누락 날짜만 추가하고 기존 성공 원본·수집 상태는 덮어쓰지 않는다.

감사 원본은 `data/rebounds/backfill-audit.json`이며 날짜별 건수·버전·체크섬·제공 범위를 보존한다. 연도별 원본과 선택 설치한 pyarrow는 Git에서 제외되는 `data/tmp_rebounds/` 등에 보관한다. 일반 수집·빌드·발행에는 pyarrow가 필요하지 않다. 재실행 예시:

```powershell
python scripts/backfill_rebounds.py --end 2026-11-05 --deps-dir data/tmp_rebounds/deps
python scripts/rebound_data.py collect
python scripts/rebound_data.py publish
```

원본 경로는 `--source-dir`을 여러 번 지정해 우선순위를 줄 수 있다. 연도별 `marcap-YYYY.parquet` 옆에 기존 수집기 형식의 `.source.json`(year/url/revision/sha256/fetched_at)을 둔다. 기본값은 `data/tmp_rebounds/source`, `data/tmp_korea_recalculation/source` 순이다.

화면에 실제 저장 범위와 과거 복원 기준을 표시했다. Python 14개·프런트엔드 8개 테스트와 TypeScript 검사를 통과했다. Vite production build는 임시 디렉터리에서 공개 대용량 파일 재복사 없이 통과했다. 실제 Chromium으로 2018/2020/2025/2026년 실데이터와 실제 0건 날짜, 최신 기록, 1440/390/320px 화면, 검색·복사·상세 이동·실패 시 보존을 검증했다. 브라우저 테스트는 `node tests/rebounds-browser.mjs`, Python 검증은 `python -m unittest discover -s tests -p 'test*rebound*.py' -v`로 실행한다. 운영 배포는 수행하지 않았다.

## 2026-11-05 운영 배포 완료

사용자 배포 요청에 따라 최신 운영 버전에 반등 기능·원본·자동 수집을 통합했다. 운영 커밋은 `463bdef003c42113da86c7d717ae4e8548f682e8`이며 [GitHub Pages 배포 실행](https://github.com/juyeop-dev/find_peer_stock/actions/runs/42026352155)의 build/deploy가 모두 성공했다. 운영 주소는 <https://juyeop-dev.github.io/find_peer_stock/rebounds>다.

배포용 체크아웃에서 Python 전체 258개, 원본 API 26개, 예약 실행 42개 테스트와 관련 프런트엔드 검사·TypeScript·전체 production build를 통과했다. 전체 산출물은 약 1.01GB이며 기존 종목 이력과 반등 2,169일을 포함한다. 운영 공개 index의 날짜·건수 전체를 검증한 목록과 대조했고, 2018-01-02·2020-03-19·2025-01-02·2026-11-02~05의 게시 원본이 수집 원본과 정확히 일치함을 확인했다. 운영 Chromium 검사도 1440/390/320px, 과거/최신/0건 기록, 검색·전체 복사·상세/복귀·실패 시 보존을 통과했다.
