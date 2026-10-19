# 화면에서 원본 자료 조회

`https://find-peer-stock-live-api.find-peer-stock-juyeop.workers.dev`는 각 페이지의 새로고침 버튼이 호출하는 Cloudflare Worker입니다. 기존 예약 실행 Worker와 별도로 동작하며, GitHub Actions나 Pages 재배포를 기다리지 않고 조회 결과를 브라우저에 반영합니다. API 키나 Cloudflare 인증 정보는 프론트엔드에 포함하지 않습니다.

## 조회 범위

- 홈과 피어 비교: 표시 대상 종목과 비교 종목의 현재가·시가총액
- 반도체 목록과 섹터 추이: 전체 종목의 현재가·일봉·확정 실적, 상세 화면에서는 해당 종목만 조회
- 신고가·거래대금 캘린더: 선택 시장의 최근 거래일 목록과 선택 날짜에 표시된 종목의 현재가
- 월별·연도별 누적 기록: 과거 집계를 보존하고 현재 표시 중인 순위 종목의 현재가 조회
- 일반 종목 상세: 해당 종목의 현재가·일봉 및 제공되는 실적
- 신용융자 잔고: 금융투자협회 최근 공표 자료

한국 주가는 Naver Finance, 해외 주가·일봉은 Yahoo Finance를 우선 사용하고 TradingView 스캐너로 보완합니다. 한국 확정 실적은 Naver Finance, 최근 신고가·거래대금 목록은 TradingView, 신용융자 통계는 금융투자협회에서 조회합니다. 제공처별 지연·휴장·공표 주기가 있으므로 조회 시각과 시세 기준 시각을 구분합니다. 외부 임베드 차트는 해당 제공처에서 다시 로드됩니다.

호출마다 원본 요청을 수행하며 응답은 캐시하지 않습니다. 프론트엔드는 현재가 최대 12개씩, 상세는 무료 서버의 처리 제한에 맞춰 1종목씩 나누어 4개 요청까지 병렬 조회합니다. 일부 조회 실패 시 성공한 필드만 갱신하고 안내를 표시하며, 전체 실패 시 기존 화면과 조회 시각을 유지합니다. 과거 캘린더 원본·누적 집계는 수정하지 않습니다. 조회 결과는 현재 브라우저 세션에 반영하며 새 문서 로드 시 배포된 스냅샷에서 시작합니다.

## 실행 및 배포

```powershell
cd automation/live-api
node --test test/*.test.mjs
npx wrangler@4.131.1 login
npx wrangler@4.131.1 deploy
```

배포 대상·허용 Origin은 `wrangler.jsonc`에 있습니다. 프론트엔드는 기본 운영 주소를 사용하며 다른 환경은 빌드 시 `VITE_LIVE_API_URL`로 지정합니다. 운영 GitHub Pages Origin과 로컬 개발 Origin만 브라우저 접근을 허용합니다. 고정된 제공처의 허용된 조회만 지원하며 임의 URL 프록시는 제공하지 않습니다. Cloudflare 인증 상태와 로컬 Wrangler 파일은 Git에서 제외합니다.

`GET /health`는 상태를, `POST /refresh`는 JSON의 `kind`에 따라 `quotes`, `details`, `scan`, `credit`를 처리합니다. `scan`에는 `market`과 `source`(`new-highs` 또는 `turnover`), 종목 조회에는 `stocks: [{ticker, exchange?}]`를 전달합니다. 이 Worker의 소스 변경은 위 명령으로 별도 배포해야 합니다.

빌드된 프론트엔드에서 모든 버튼과 실패 시 보존 동작을 검증합니다.

```powershell
cd ../../frontend
npm.cmd run build
npm.cmd run test:live-refresh:browser
$env:STOCK_LIVE_REFRESH_NETWORK = "1"
npm.cmd run test:live-refresh:browser
```

두 번째 실행은 모의 응답 검증에 이어 실제 Worker로 단일 종목 및 전체 반도체 종목을 조회합니다. Chrome 또는 Edge가 필요하며 실행 경로는 `BROWSER_PATH`로 지정할 수 있습니다.
