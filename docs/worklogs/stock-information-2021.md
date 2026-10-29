# 2021년 전체 데이터 확장

사용자 요청: 2021-01-01~2021-12-31의 전체 데이터 갱신. 이전 대화에서 승인한 사이트·원본 조회 API 배포 범위도 이어서 적용한다. 신고가·거래대금 6개 시장, 국내 섹터, 종목별 차트·확정 실적, 수급·동일 날짜 지수 및 신용융자 잔고를 갱신한다. 2022년 이후 원본은 유지한다.

작업 폴더는 `data/tmp_2021/worktree`인 별도 Git worktree다. 시작 운영 커밋은 `e26b4bd35`. 원래 작업 폴더의 미커밋 생성 파일은 수정하거나 되돌리지 않는다. 기존 원본 12,039개 해시와 가격·실적·수급·신용·반도체 자료는 이 작업 폴더의 `data/tmp_2021/baseline`에 보존했다.

## 원본 기준

- 공식 휴장 일정은 `data/market-closures/2021.json`, 유럽 거래소별 휴장은 `data/new-highs/europe-exchange-closures.json`에 기록한다. 일본의 올림픽에 따른 공휴일 이동을 정부 원본과 대조했다. 대만은 TWSE Fact Book의 12개월별 거래일 수와 대조하며 4/30 근로자의 날 대체휴일을 포함한다.
- 예상 거래일: 한국 248일, 미국 252일, 일본 245일, 대만 244일, 중국 243일, 유럽 258일. 각 캘린더는 총 1,490개 일별 보고서다.
- 국내 시가총액·거래대금은 FinanceData/marcap 고정 revision `eeed0817d1478597b738a3a6149c170ec7e3f4cb`의 2021 Parquet를 사용한다. 원본 SHA256과 길이는 `data/tmp_korea_recalculation/source/marcap-2021.source.json`에 기록한다. 주가×주식 수와 시총 단위를 검증한다.
- 미국·일본·대만·중국의 일봉·월봉은 Yahoo를 우선 사용한다. 유럽은 2,000개 일봉을 요청해 2021년 초의 52주 비교 구간을 확보한다. 동일 상장 코드·거래소·회사·통화를 검증하며 유럽의 부분 복원 안내를 유지한다.
- 대만 Yahoo 원본은 공식 거래일인 **2021-04-06을 모든 종목에서 누락**했다. 짧은 날짜 범위로 재조회한 TSMC도 동일했다. 이 날을 휴장으로 바꾸지 않는다. `recover_taiwan_calendar_gap.py`가 검증된 동일 거래소 TradingView 실제 일봉·전체 월봉으로 신고가와 거래대금을 별도 복원한다. 원본 간 조정 방식을 임의로 섞거나 가격을 보간하지 않는다.
- 이미 받은 일봉은 종목·통화·겹치는 실제 가격을 검증한 후 이전 구간만 추가한다. 새 제공처가 이전 값을 생략하거나 수정하면 원본 스냅샷을 유지한다. 가격 없는 날짜와 미제공 실적·분기를 만들어 넣지 않는다.

## 재개

`data/tmp_2021/*.log`와 `*.process.json`에 각 수집 프로세스의 로그·PID·명령을 기록했다. `data/tmp_calendar_history`, `data/tmp_korean_history`, `data/tmp_tradingview_chart`, `data/tmp_korea_recalculation`은 기존 검증 캐시를 가리키는 junction이다. 원본 범위별 캐시 키와 파일 SHA256을 유지한다. WebSocket 의존성은 원래 작업 폴더의 `data/tmp_info_update/deps`를 `PYTHONPATH`로 사용한다.

```powershell
python scripts/backfill_stock_information_2021.py collect --workers 12
python scripts/backfill_stock_information_2021.py export
python scripts/extend_stock_history_2021.py
python scripts/refresh_stock_information_history.py --state-dir data/tmp_2021_history
node scripts/backfill_investors_2021.mjs
python scripts/backfill_credit_2021.py
python scripts/backfill_semiconductor_history_2021.py
python scripts/recover_taiwan_calendar_gap.py --date 2021-04-06
python scripts/backfill_sector_history_2021.py
python scripts/recalculate_korea_history.py --start 2021-01-01 --end 2021-12-31 --audit-tag 2026-10-29-2021 --apply
python scripts/audit_calendar_2021.py
python scripts/audit_stock_information_2021.py
```

## 수집 및 검증

- 국내 수급·지수 248일, KOFIA 신용융자 잔고 249개 보고일, 국내 섹터·KRX 확정 거래대금 248일을 복원했다. 국내 시총·거래대금 재계산의 누락 원본 날짜는 없다.
- 반도체 102종목과 전체 상세 종목의 2021년 일봉을 확장했다. 대만 4/6은 1,831개 실제 관측 상장 종목으로 신고가 186개·거래대금 30개를 복원했다. 차트 1,802개는 동일 거래소의 전체 조정 곡선을 사용하며 기존 가격은 별도 원본 스냅샷으로 보존한다. 최신 날짜가 더 짧은 9개 대체 곡선은 별도 스냅샷으로 보존하고 현재 곡선의 더 최신 관측을 유지한다.
- Yahoo OHLCV는 이미 분할 조정된 값이다. 기존 수집기의 중복 분할 조정을 수정하고 새로 수집한 2021년 해외 보고서만 재생성했다. NVDA 2021년 7월, Toyota 2021년 9월의 분할 전후를 확인했다. 기존 2022년 이후 보고서는 변경하지 않았다.
- 과거 범위가 실제 상장일보다 빠르면 Yahoo가 HTTP 400을 반환한다. 현재 동일 코드·회사·통화·주식 유형과 실제 최초 거래일을 검증해 이후 상장만 제외한다. 거래소별 최소 70% 수집 기준은 낮추지 않는다.
- Yahoo의 과거 실적 제공 한계가 있어 SEC 공개 원본도 확인했으나 HTTP 403으로 접근할 수 없었다(`sec-source-check.json`). 회사 공식 GAAP 발표의 연간 실적 4개(AAPL, NVDA, MU, AMD)를 USD 백만 단위에서 원 단위로 환산해 보완했다. 근거·회계연도 말일·발표일은 `data/seed/reported_financials_2021.json`에 있다. 연간 실적을 임의 분기로 나누지 않는다. 그 밖의 원본 미제공 종목은 예외 목록에 남긴다.
- 2025년까지 일별 공개 신고가·거래대금 파일은 무손실 gzip으로 발행해 Pages 용량을 확보한다. 원본 `data/*/reports` JSON과 숫자는 그대로다. 이전 공개 JSON 사본은 개별 SHA256 백업으로 이동하며 삭제하지 않는다. 브라우저는 압축 응답·호스트 자동 해제·기존 JSON 대체 경로를 모두 지원한다. 2026년 이후 주소는 JSON이다.
- 기존 확정 실적은 새 원본 조회 후에도 보존하며 합쳐진 실제 실적에서 연도별 표시 건수를 다시 계산한다.
- Python 219개, 프런트엔드 36개, API 24개 테스트와 TypeScript 검사가 통과했다.
- 보존 검사: 기존 원본 12,039개 SHA256 동일, 이전 확정 실적 204,376개 동일, 이전 차트 가격 24,040,671개와 반도체 102종목 보존, 수급 1,178일·신용 1,181개 보고일 동일(`preservation.json`).
- API 운영 배포 버전: `ce84f8b1-f58b-4544-aa4f-a9de8f1c5895`. 실제 TSMC 일봉 첫 날짜 2020-12-21, 2021년 확정 연간 실적 1개 응답을 확인했다(`api-production.json`).

최종 전수 감사 및 배포 검증 기록은 아래에 이어서 기록한다.

## 최종 전수 감사

- 상세 종목 **24,433개 모두 확인**, 실적·일봉 수집의 다음 미처리 항목은 없다. 2021년 확정 실적이 확인된 종목 16,428개, 제공처 미제공 8,005개다. 확인되는 분기 원본이 없어 연간 실적을 분기로 나누지 않았다.
- 차트: 2021년 이전부터 관측 18,480개, 이후 상장 5,116개, 원본 범위 제한 819개, 기존 미제공 차트 18개. 예외 목록은 `data/information-audit/2021/coverage-exceptions.json`이며 미제공을 완전 수집으로 표시하지 않는다.
- 신고가·거래대금 각각 한국 248일, 미국 252일, 일본 245일, 중국 243일, 대만 244일, 유럽 258일로 공식 거래일과 정확히 일치한다. 각 1,490일이며 국내 섹터·수급·지수 248일, 신용 보고일 249개를 검증했다.
- 미국 현재 스캐너 5,711종목 중 1,388개는 2021년 이후 상장 등 요청 구간 외인 것을 확인했다. 미확인 원본 1개(SLMT)는 제외하고 원래의 거래소별 수집률 검사를 통과했다. 현행 상장 명단을 사용하는 해외 복원의 상장폐지 종목 제외 한계는 보고서에 유지한다.

## 로컬 배포 검증

- 운영 경로 `/find_peer_stock/`로 빌드 성공, SPA 대체 페이지 포함 88,524파일·**840.53 MiB**, Pages 1 GiB 한도 이하(`build-validation.json`).
- 2021~2025년 압축 보고서 **11,870개**를 생성 원본 JSON과 전체 대조해 숫자·정밀도·내용이 동일함을 확인했다.
- 2021년 브라우저: 두 종류 × 6개 시장의 연간·7개월 캘린더, 유럽 부분 복원 안내, 국내 섹터 분류 기준 안내, 상세 화면 8개, `2021년~` 가격 구간과 확정 실적, 신용 잔고, 원본 정보·일봉 재조회, 1440/320px를 통과했다.
- 투자자 수급: 정확한 날짜별 매수·매도·순매수와 두 지수, 시장 합계, 휴장일·URL, 원본 재조회 실패 시 기존 값 유지, 1440/390/320px 통과. 2022년 캘린더·상세 화면 8개·원본 재조회도 압축 발행 후 회귀 검증을 통과했다(`local-validation.json`).

## 운영 배포 완료

- 기능 커밋 `ccf5c571d`, 최신 자동 갱신과 합친 배포 커밋 `93e2546b305331f5cb07ca5a2cf77bdbc3ea0cb8`.
- [운영 빌드·Pages 배포 40875933958](https://github.com/juyeop-dev/find_peer_stock/actions/runs/40875933958)의 두 작업 모두 성공했다. API 버전은 위 `ce84f8b1-f58b-4544-aa4f-a9de8f1c5895`다.
- 실제 사이트의 두 캘린더 × 6개 시장 거래일 수, 12개 공개 압축 보고서의 과거 원본 값, 수급 248일·신용 보고일 249개, TSMC 차트의 4/6 실제 관측, AAPL·NVDA·MU·AMD 공식 연간 실적을 확인했다(`site-production.json`). 신고가 화면의 별도 **현재 시총** 5개 보강 필드는 배포 시 새로 조회되는 값으로 구분했고, 과거 신고가 관측과 날짜가 지정된 거래대금 시총은 원본과 정확히 대조했다.
- 운영 주소에서 2021년 캘린더·상세 화면 8개·신용잔고·실적·원본 재조회·모바일 검증을 통과했다. 운영 수급·지수의 실제 2021년 재조회와 실패 시 기존 값 유지도 통과했다(`production-validation.json`).
- 기존 작업 폴더의 생성 파일은 보존하고, 별도 작업 폴더 `data/tmp_2021/worktree`에서 수집·검증·배포했다.
