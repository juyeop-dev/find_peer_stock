# 2014년 데이터 확장

## 운영 배포 완료 (2026-11-15)

2014년 자료를 [운영 사이트](https://juyeop-dev.github.io/find_peer_stock/)와 API에 배포했고 실제 운영 데이터·상세 화면·수급 화면 검사를 모두 통과했다. [GitHub Actions](https://github.com/juyeop-dev/find_peer_stock/actions/runs/43709606727)의 최종 결과는 성공이며 배포 커밋은 `ae73fbf8943bafc544e99a67a575da4616b52d6c`다. API 버전은 `9a39848e-a586-455d-baeb-48e84b350930`다.

6개 시장 신고가·거래대금은 각각 1,490거래일, 국내 섹터·수급·지수·반등은 245거래일, 신용융자는 246보고일을 추가했다. 25,164종목을 감사하고 2,462종목의 확정 실적 8,531분기를 반영했다. 가격 범위는 2014년 포함 12,859종목·이후 상장 11,483종목·제공 범위 제한 802종목·자료 부족 20종목으로 구분한다. 미제공 가격·실적을 추정하지 않는다.

Python 287·API 27·프런트엔드 54개 및 TypeScript 검사를 통과했다. 2014~2017년 전체 공개 원본 대조와 실제 운영 브라우저의 8개 상세 경로·달력·갱신·모바일 검사를 통과했다. 게시 전 최종 묶음은 116,695파일·933,153,641바이트다. 공개 주 곡선에서 13,821종목의 2014년 원본 관측일과 대만 토요일 실제 가격 1,293개를 독립 대조했다. 증빙은 `data/information-audit/2014/deployment.json`, `site-production.json`, `api-production.json`, `production-*-check.json`이다.

## 공식 달력과 실제 원본

시장별 거래일은 한국 245·미국 252·일본 244·중국 245·대만 248·유럽 256일이다. 대만은 7월 23일 태풍 휴장과 12월 27일 토요일 개장을 반영했다. 중국 1월 30일은 개장일이며 유럽은 개별 거래소 휴장 차이를 유지한다.

대만은 [TPEx 공식 달력](https://www.tpex.org.tw/storage/en-us/web/bulletin/trading_date/trading_date_103.htm)과 [증권상업협회 공식 기록](https://www.twsa.org.tw/B01/doc/104Q1.pdf)을 대조했다. TWSE·TPEx 12월 26·27·29일 원본의 종목·OHLC·조정 비율을 확인해 토요일 가격 1,293개를 복구했다. 대상 1,363개 중 미검증 70개는 제외 사유를 남겼다. 토요일 실제 거래대금 상위 30개와 인접 거래일의 이전 종가·신고가 분류도 독립 검증했다. 공식 휴장일 제공처 값은 일반 차트에서 제외하되 변경하지 않은 전체 원본을 별도 보존한다.

그 밖의 공식 근거는 [NYSE 일정](https://ir.theice.com/press/news-details/2013/NYSE-Euronext-Announces-2015-Holiday-Calendar-and-Early-Closings/default.aspx), [상하이거래소 공고](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988725.shtml), [Euronext 일정](https://www.euronext.com/en/about/media/euronext-press-releases/nyse-euronext-announces-its-2014-holiday-calendar-and-early), [Xetra 달력](https://www.xetra.com/resource/blob/281576/967747fbc75fa120c2142e05d2e40711/data/trading-calendar-2014.pdf)이다. 원문·URL·SHA256은 `data/tmp_2014/sources`에 보존했다.

## 원본 보존과 데이터 범위

기존 원본 파일 37,627개, 가격 53,433,422개, 확정 실적 310,420행, 현재 종목 스냅샷 29개를 보존했다. 기존 신용 2,922행·수급 2,912행·반도체 114종목·리플레이 13,318봉도 보존 검사를 통과했다. 다른 가격 조정 기준의 원본은 임의로 이어 붙이지 않고 독립 보관한다. 검증된 관측일 보완은 1,454종목에 적용했다.

반도체 보존 원본은 `data/semiconductor/preserved-snapshots/*.json.gz`의 114개 불변 파일에 보관한다. 1,220개 이전 스냅샷·관측값 1,920,132개와 모든 메타데이터를 기존 자료와 동일하게 복원하는지 검증했다. `semiconductor_provenance.py`가 SHA256·종목·개수·경로를 검증하며 수집·게시 과정에서 오류를 전파한다. 이후 연도 확장 때 주 JSON과 참조 압축 원본을 함께 보존해야 한다.

신규 상장이나 제공처 미제공 자료는 실제 관측 기간·명시적 사유로 구분한다. 접근 제한·연결 오류·수집기 오류를 원본 없음으로 처리하지 않는다. 일봉이 아닌 월봉·연봉이나 종목이 다른 매핑을 거부한다. 미제공 가격·분기 실적은 추정하지 않는다. 실시간 제공처의 과거 실적 부재로 이미 저장한 실제 공시를 지우지 않는다.

## 배포 파일과 재현 검증

배포 결과물의 가격은 `stock-history-delta-v1` 형식과 `.delta-v1.json.gz` 주소를 사용한다. 실제 날짜 간격과 중복 조정 종가만 압축하며 가격 반올림·날짜 보간·관측값 삭제를 하지 않는다. 원본과 공개 준비 JSON은 유지한다. TypeScript 복원기로 실제 클라이언트를 검증하고 모든 최종 파일을 원본과 대조했다. 구 클라이언트와 주소가 충돌하지 않도록 버전 주소를 쓰며 기존 gzip·JSON 주소도 읽을 수 있다.

최종 공개 가격 57,477,905개에는 국내 대체 곡선이 포함된다. 연속 가격 파일 25,168개와 실적 파일 25,165개는 상세 목록 밖의 독립 원본 검증용 보관 종목도 포함하므로 감사 목록 수와 다를 수 있다. 전체 묶음은 1 GiB 미만이다. 정상 자동 갱신과 준비된 스냅샷 게시 모두 2014~2017년 공개 원본 대조를 통과해야 배포한다.

증빙 경로는 다음과 같다.

- `coverage.json`, `coverage-results.json`, `coverage-exceptions.json`: 종목별 가격·확정 실적 범위.
- `calendar-coverage.json`, `calendar-source-quality.json`, `daily-frequency-audit.json`, `taiwan-quality.json`: 거래일·실제 일봉·독립 대만 원본 검증.
- `preservation.json`, `historical-display-retention.json`, `observation-date-repair.json`, `semiconductor-source-archive.json`: 기존 원본·화면 관측값·반도체 보존.
- `source-price-calendar.json.gz`, `publication.json` 및 기존 연도 `publication.json`: 원본 관측일과 모든 공개 가격·실적·달력 대조.
- `deployment.json`, `site-production.json`, `api-production.json`, `production-*-check.json`: 실제 게시 결과와 운영 데이터·브라우저 검증.

위 파일은 모두 `data/information-audit/2014` 아래에 있다. 실제 운영 검사는 6개 시장 달력, 2014년 Apple 공시, 대만 토요일 가격·거래대금, 신용·섹터·리플레이와 8개 상세 경로를 확인했다. 수급은 같은 날짜의 코스피·코스닥 지수 및 매수·매도·순매수, 달력·URL 선택, 원본 재조회, 실패 시 보존, 1440·390·320px 화면을 검사했다.
