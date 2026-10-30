# 2019년 전체 데이터 갱신

사용자 요청: 2020년과 동일한 범위로 2019년 자료 확장. 신고가·거래대금 6개 시장, 종목 차트·확정 실적, 국내 섹터·투자자 수급·동일 날짜 지수·신용잔고를 포함한다.

직전 2020년 운영 배포는 완료됐다. 사이트 `https://juyeop-dev.github.io/find_peer_stock/`, Pages 실행 `41021084218`, API 버전 `1e7bd3c4-ec8c-4269-b5fa-876fbd1682d2`다. 공개 값·8개 상세 화면·실제 원본 조회·모바일 검증을 통과했다. 증빙 커밋은 `d5b86e03f`다.

## 작업 및 보존

- 작업 폴더: `data/tmp_2019/worktree`, 배포 기준 `b0c2450a2d2c81b30f1544dd24ef8ff31fa11508`, 작업 브랜치 `history-2019`.
- 기존 일별 원본 SHA256, 실적·일봉·반도체·수급·신용은 작업 폴더의 `data/tmp_2019/baseline`에 보관했다. 원래 작업 폴더와 2020년 운영 자료는 보존한다.
- 원본 캐시는 기존과 공유하지만 2019년 요청 범위는 별도 키를 사용한다. 실적 수집은 `data/tmp_2019/information.sqlite`, 가격 확장은 `data/tmp_2019_history`에서 재개한다.
- KRX 금액·시총 원본은 FinanceData/marcap 고정 revision `eeed0817d1478597b738a3a6149c170ec7e3f4cb`의 2019년 Parquet이다. 공유 캐시 `data/tmp_korea_recalculation/source/marcap-2019.source.json`에 출처·SHA256을 기록했다.

## 날짜 기준

공식 거래일 예상 수는 한국 246, 미국 252, 일본 241, 중국 244, 대만 242, 유럽 256이다. 일본 즉위 관련 4일 추가 휴장, 중국 노동절 변경, 대만 8/9·9/30 태풍 전면 휴장을 반영했다. 반일장은 거래일이다. 유럽 개별 거래소 휴장은 별도로 대조한다. 근거는 `data/market-closures/2019.json`과 `data/new-highs/europe-exchange-closures.json`에 기록했다.

## 수집 진행 및 재개

초기 실행 도구는 원래 작업 폴더의 `data/tmp_2019/launch.py`다. 각 수집기의 명령·PID·시작 시각과 로그는 작업 폴더의 `data/tmp_2019/*.process.json`, `*.log`에 있다.

- 신용잔고 247개 보고일과 수급·동일 날짜 지수 246거래일 수집 완료.
- 반도체 102종목의 2019년 일봉 확장 완료. 다른 조정 가격은 이전 원본 스냅샷으로 보존했다.
- SEC 원본 3,210종목·13,721행 수집 완료. 실제 회계기간·CIK·회사·거래소·USD 단위를 검증하고 연간·누적 실적에서 분기를 추정하지 않는다. 전체 실적 수집 후 적용한다.
- 전체 종목 실적 및 6개 시장의 신고가·거래대금 수집을 완료했다. 제공처 미지원·상장일 이전 구간은 예외로 구분하며 값이나 거래일을 추정하지 않는다.
- 대만 Yahoo의 2019-09-09 일봉이 전체 종목에서 빠진 것을 발견했다. TWSE 원본으로 실제 거래를 확인했다(`taiwan-source-check.json`). `recover_taiwan_calendar_gap_2019.py --date 2019-09-09`로 완전한 동일 거래소 TradingView 곡선을 수집하며, 휴장이나 보간값으로 대체하지 않는다. 완료 후 `import_taiwan_gap_histories_2019.py`를 실행한다.
- API 26개, Python 230개 테스트 통과. 프런트엔드 타입 검사 통과. 수급 테스트의 첫 날짜·연간 건수는 새 2019년 자료에 맞춰 확장했다.

주요 후속 명령(앞 단계 완료·전수 검증 후 순서대로 실행):

```powershell
python scripts/backfill_stock_information_2019.py collect --workers 12
python scripts/backfill_sec_financials_2019.py apply
python scripts/backfill_stock_information_2019.py export
python scripts/backfill_european_turnover.py --start 2019-01-01 --end 2019-12-31 --daily-bars 2800 --partial-history
python scripts/extend_stock_history_2019.py
python scripts/refresh_stock_information_history.py --state-dir data/tmp_2019_history --import-europe-cache --extend-to-start
python scripts/backfill_sector_history_2019.py
python scripts/recalculate_korea_history.py --start 2019-01-01 --end 2019-12-31 --audit-tag 2026-10-30-2019 --apply
python scripts/audit_calendar_2019.py
python scripts/audit_stock_information_2019.py
python scripts/audit_preservation_2019.py
```


## 수집 및 전수 감사 완료

- 전체 24,810종목의 조회를 마쳤다. 확정 실적 확인 3,212종목, 매출 2,617종목, 영업이익 2,530종목, 실제 분기 10,531건이다. 미제공 21,598종목은 예외 목록에 남겼다. `coverage.json`, `coverage-exceptions.json`에 종목별 근거가 있다.
- 차트: 2019년 초부터 관측 17,108종목, 이후 상장 6,757종목, 원본 범위 제한 927종목, 원본 미제공 18종목이다. IPO 이전이나 제공처 미지원 구간을 추정하지 않는다.
- 두 캘린더 각각 한국 246·미국 252·일본 241·중국 244·대만 242·유럽 256일, 합계 1,481일이다. 국내 섹터·수급·동일 날짜 지수 246일과 신용 보고일 247개를 검증했다(`calendar-coverage.json`).
- 중국 Yahoo의 4/29·4/30 누락도 실제 동일 거래소 곡선으로 복원했다. B주의 USD·HKD 가격 단위는 유지하고 거래대금만 같은 날짜 관측 환율로 CNY 환산했다. 복원한 곡선은 대만 1,694·중국 3,436종목의 주 가격 이력에 반영했으며, 오래된 대체 곡선은 각각 1개씩 별도로 보존했다. 가격 조정 기준은 섞지 않았다(`recovered-price-curves.json`).
- 유럽 환율의 2019-05-22 Yahoo 정·역환율 누락은 같은 날짜의 중앙은행 원본으로 대조했다. 캐나다 중앙은행은 실제 공표 일평균, ECB는 실제 공표 기준환율임을 구분하고 출처·원본 SHA256·관측 날짜·통화 단위를 기록했다. 이전 날짜 값을 이월하지 않았다.
- 기존 일별 원본 18,501개 SHA256, 확정 실적 245,820행, 주 가격 관측 34,023,909개, 수급 1,675일·신용 1,680개 보고일과 반도체 102종목을 보존했다(`preservation.json`).
- 종목 정보는 원본 JSON을 무손실 gzip으로 발행한다. 압축·호스트 해제·기존 JSON 경로와 0·음수·유니코드·숫자 정밀도 보존을 검증했다. 불연속 보존본은 저장소에 유지하며 화면에서 쓰는 완전한 가격 곡선은 계속 발행한다.

## 로컬 검증 및 작업 폴더 반영 완료

- Python 235개, API 26개, 프런트엔드 39개 테스트와 타입 검사를 통과했다. 기존 2020년 브라우저 회귀 검사도 통과했다.
- 2019년 두 캘린더 × 6개 시장, 상세 화면 8개·`2019년~` 가격·확정 실적 또는 미제공 안내·신용잔고·실제 원본 재조회와 모바일 검증을 통과했다. 날짜별 수급·두 지수·시장 합계·실패 시 값 보존·1440/390/320px, 은행 섹터·정식 종목명·26개 정렬·1440/320px도 통과했다(`local-validation.json`).
- 같은 시작일로 재조회해도 중간에 복원한 거래일을 잃지 않게 했다. 가격 조정 기준이 일치하는 관측만 합치고, 다르면 저장된 연속 곡선을 유지한다.
- 최종 운영 묶음 955.64 MiB, 96,167파일로 한도 이내다. 공개 과거 보고서 17,810개를 생성 원본과 전수 대조했다(`production-artifact.json`). 공개 가격 파일에는 주 곡선과 실제 국내 섹터 조회에 필요한 완전한 대체 곡선만 포함하며 모든 보존 관측은 저장소 원본에 유지한다.
- 원래 작업 폴더에 6,546파일을 반영했다. 기존 작업 폴더의 확정 실적 243,381행, 주·보존 가격 관측 40,174,718개를 유지했다. 기존 현재 시세·인덱스·피어 파일은 보존하며 원래 값이 다른 실적은 원본 보존본으로 구분한다(`original-workspace-preservation.json`).


## 운영 배포 완료

- 배포 커밋 `e44c9537448aee496a0741e39eb239428020f179`. [GitHub Pages 실행 41033223061](https://github.com/juyeop-dev/find_peer_stock/actions/runs/41033223061)의 빌드와 공개가 모두 성공했다.
- 운영 사이트: https://juyeop-dev.github.io/find_peer_stock/ . 운영 API: https://find-peer-stock-live-api.find-peer-stock-juyeop.workers.dev . API 버전 `344c3828-3d33-4737-a50e-66a56003363d`를 배포했다.
- 운영 API에서 일봉 시작 `2018-12-20`, 2019년 실적 조회 범위와 기존 2020년 범위 유지, 2019-01-02 코스피·코스닥 수급 및 동일 날짜 지수 2,010 / 669.37을 확인했다(`api-production.json`). 원본의 미제공 실적은 저장된 SEC 실적을 대체하지 않는다.
- 공개 사이트에서 두 캘린더 × 6개 시장의 2019년 거래일 수와 보고서 12개의 원본 값, 섹터·수급 246일과 신용 247개 보고일을 대조했다. 미국 4종목의 2019년 SEC 실적·가격, 대만 9/9와 중국 4/29·4/30의 복원 가격도 확인했다(`site-production.json`).
- 공개 브라우저에서 연간·월별 캘린더, 상세 8개, 2019년부터의 차트, 확정 실적 또는 미제공 안내, 신용잔고, 실제 원본 정보·가격 재조회와 모바일 검증을 통과했다. 2019년 수급·지수의 실제 원본 재조회와 실패 시 기존 값 보존도 통과했다(`production-validation.json`).
- 원래 작업 폴더 반영과 운영 경로 빌드도 완료했다. 최종 로컬 운영 묶음은 955.64 MiB이며 기존 원본을 보존했다. 제공처 범위 제한과 미제공 실적은 명시적으로 안내한다.
