# Stock Peer Site 계획서

## 방향

특정 종목과 peer 기업들의 주가 정보를 보여주는 웹 사이트를 만든다. 1차 MVP는 **백엔드 없이 React 정적 사이트 + GitHub Actions JSON 재생성** 방식으로 구현한다.

FastAPI는 당장 배포하지 않는다. 대신 데이터 파일 구조와 프론트엔드 API client를 FastAPI로 자연스럽게 전환할 수 있게 설계한다. 나중에 사용자가 누르는 즉시 가격 갱신, 서버 캐시, 시가총액/순위, 검색 인덱스가 필요해지면 FastAPI를 붙인다.

## 1차 MVP 범위

- React + TypeScript + Vite 프론트엔드
- GitHub Actions가 5분마다 실행되고, 장이 열린 시장의 가격 JSON만 재생성
- 종목 상세 페이지는 1분마다 정적 JSON을 다시 확인하고 변경 시 화면 자동 갱신
- 프론트엔드는 생성된 JSON을 읽어서 화면 표시
- 종목 상세 화면 우선 구현
- 메인 화면은 지수 카드 뼈대만 구현
- PC 화면 우선
- 모바일 최적화는 이후 단계
- 시가총액 및 시가총액 순위는 이후 단계
- FastAPI는 폴더/인터페이스 설계만 하고 실제 배포는 보류

## 백엔드 없는 구조를 선택한 이유

초기 요구사항 대부분은 정적 JSON으로 처리할 수 있다.

- 종목 기본 정보 표시
- peer 그룹 표시
- peer 기업명 클릭 후 상세 페이지 이동
- 현재가/전일 대비/조회 시각/출처 표시
- 장중 5분 단위 가격 갱신
- 브라우저 1분 단위 JSON 자동 확인
- GitHub Pages 또는 정적 호스팅 배포

초기에는 수동 새로고침 버튼을 노출하지 않는다. 백엔드가 없는 정적 사이트에서는 버튼을 눌러도 외부 가격 데이터를 즉시 다시 가져올 수 없고, 현재 배포되어 있는 최신 JSON을 다시 fetch하는 동작만 가능하기 때문이다.

나중에 FastAPI를 붙이면 종목 헤더에 아래 버튼을 추가해서 진짜 즉시 갱신으로 연결한다.

```text
최신 가격 가져오기
```

## 기술 스택

초기:

- Frontend: React + TypeScript + Vite
- Styling: 일반 CSS 또는 CSS Modules
- Data generation: Python script
- Automation: GitHub Actions
- Hosting: GitHub Pages 우선 검토

나중:

- Backend: FastAPI + Python
- Cache: 메모리 캐시 -> SQLite/Redis/Postgres 중 선택
- Backend hosting: Render, Koyeb, Cloud Run 중 선택

## 프로젝트 폴더 구조 초안

```text
stock_peer_site/
  PLAN.md
  README.md
  data/
    seed/
      peer_alerts/
        samsung_electronics.json
        samsung_electro_mechanics.json
        sk_hynix.json
        ls.json
    generated/
      index.json
      stocks/
        005930.KS.json
        009150.KS.json
        000660.KS.json
        006260.KS.json
  scripts/
    generate_static_data.py
    quote_sources/
      korea_quote.py
      taiwan_quote.py
      yahoo_quote.py
  frontend/
    public/
      data/
        index.json
        stocks/
    src/
      app/
      pages/
      components/
      dataClient/
      styles/
      types/
    package.json
    vite.config.ts
  backend/
    README.md
    app/
      main.py
      api/
      models/
      services/
  .github/
    workflows/
      build-site.yml
      refresh-data.yml
```

초기 구현에서 `backend/`는 실제 앱 구현 대상이 아니다. 향후 FastAPI로 전환할 때 필요한 API 계약과 설계 메모를 두는 정도로 유지한다.

## 데이터 흐름

초기 MVP:

```text
GitHub Actions schedule
  -> Python 가격 수집 스크립트 실행
  -> data/generated/*.json 생성
  -> frontend/public/data/*.json에 복사
  -> React build
  -> GitHub Pages 배포

사용자 브라우저
  -> /data/index.json fetch
  -> /data/stocks/{ticker}.json fetch
  -> 종목 상세 페이지는 1분마다 해당 JSON 재확인
  -> 화면 렌더링
```

나중에 FastAPI 전환:

```text
사용자 브라우저
  -> /api/stocks/{ticker}/summary fetch
  -> FastAPI가 캐시 확인
  -> 필요 시 가격 소스 조회
  -> 화면 렌더링
```

프론트엔드는 `dataClient`를 통해 데이터만 받는다. 정적 JSON이든 FastAPI든 화면 컴포넌트는 같은 타입을 사용한다.

## 핵심 화면

### 1. 메인 화면

초기에는 뼈대만 만든다.

나중에 표시할 정보:

- 코스피 지수
- 코스닥 지수
- 일본 지수
- 대만 지수
- 중국 지수
- 미국 지수
- 주요 관심 종목 바로가기

초기 PC UI 방향:

- 상단: 사이트 제목, 검색창, 마지막 데이터 생성 시간
- 본문: 시장별 지수 카드 영역
- 하단 또는 우측: 관심 종목 리스트
- 지수 데이터가 없으면 `준비 중` 상태로 표시

### 2. 종목 상세 화면

URL 예시:

```text
/stocks/005930.KS
/stocks/MU
/stocks/2330.TW
```

표시 정보:

- 종목명: 삼성전자
- 티커: `005930.KS`
- 테마: 메모리 / HBM / NAND / 파운드리
- 현재 가격: `296,000 KRW`
- 전일 대비: `+12,000 KRW (+4.23%)`
- 데이터 출처
- 가격 조회 시각
- 수동 새로고침 버튼은 숨김
- peer 그룹별 기업 리스트

시가총액 및 시가총액 순위는 화면 자리는 남겨두되, 초기 구현에서는 미표시 또는 `준비 중`으로 처리한다.

## 종목 상세 UI 구성

PC 우선 레이아웃:

```text
상단 영역
  - 뒤로가기 또는 breadcrumb
  - 종목명 / 티커 / 국가 / 테마
  - 수동 새로고침 버튼은 숨김

가격 요약 영역
  - 현재가
  - 전일 대비 금액
  - 전일 대비 %
- 가격 조회 시각
- JSON 생성 시각
- 시장 상태
- 출처

기업 정보 영역
  - 텔레그램 봇 config의 target/theme/market_note 기반 설명
  - 시가총액, 순위 자리만 예약

Peer 영역
  - 그룹별 섹션
  - peer 기업 카드 또는 테이블
  - 기업명 클릭 시 해당 종목 상세 페이지로 이동
```

Peer 카드/테이블 컬럼:

- 기업명
- 티커
- 국가
- 사업 메모
- 현재가
- 전일 대비
- 전일 대비 %
- 마지막 가격 조회 시각
- 데이터 출처

## 정적 JSON 모델

정적 JSON은 나중의 FastAPI `GET /api/stocks/{ticker}/summary` 응답과 최대한 같은 모양으로 둔다.

### `frontend/public/data/index.json`

```json
{
  "generated_at": "2026-05-14T06:30:12+09:00",
  "stocks": [
    {
      "id": "samsung_electronics",
      "ticker": "005930.KS",
      "name_kr": "삼성전자",
      "theme": "메모리 / HBM / NAND / 파운드리",
      "summary_path": "/data/stocks/005930.KS.json"
    }
  ],
  "market_indices": []
}
```

### `frontend/public/data/stocks/{ticker}.json`

```json
{
  "generated_at": "2026-05-14T06:30:12+09:00",
  "company": {
    "id": "samsung_electronics",
    "name_kr": "삼성전자",
    "name_en": "Samsung Electronics",
    "ticker": "005930.KS",
    "country": "한국",
    "theme": "메모리 / HBM / NAND / 파운드리",
    "market_note": "메모리·파운드리 peer 가격 확인"
  },
  "quote": {
    "ticker": "005930.KS",
    "price": 296000,
    "currency": "KRW",
    "change": 12000,
    "change_pct": 4.23,
    "source": "Naver Finance",
    "fetched_at": "2026-05-14T06:30:12+09:00",
    "market_time": "2026-05-14T15:30:00+09:00"
  },
  "peer_groups": [
    {
      "group": {
        "emoji": "🧠",
        "name": "DRAM / HBM",
        "summary": "메모리 peer"
      },
      "peers": [
        {
          "company": {
            "name_kr": "마이크론",
            "name_en": "Micron Technology",
            "ticker": "MU",
            "country": "미국",
            "note": "DRAM·HBM"
          },
          "quote": {
            "ticker": "MU",
            "price": 110.5,
            "currency": "USD",
            "change": 2.1,
            "change_pct": 1.94,
            "source": "Yahoo Finance",
            "fetched_at": "2026-05-14T06:30:12+09:00",
            "market_time": "2026-05-13T16:00:00-04:00"
          },
          "summary_path": "/data/stocks/MU.json"
        }
      ]
    }
  ],
  "sources": ["Naver Finance", "Yahoo Finance"]
}
```

`generated_at`은 GitHub Actions가 파일을 만든 시간이다. `quote.fetched_at`은 해당 quote를 실제로 가져온 시간이다. 장이 닫힌 시장은 이전 quote를 재사용하므로 `generated_at`은 바뀌어도 `quote.fetched_at`은 마지막 실제 조회 시각으로 남을 수 있다.

## 가격 업데이트 정책

초기 정적 MVP:

- GitHub Actions가 5분마다 실행된다.
- Python 스크립트는 ticker별 국가와 장 운영시간을 보고 장중인 시장만 외부 가격 소스에 요청한다.
- 장이 닫힌 시장은 외부 조회를 하지 않고 기존 JSON의 quote를 재사용한다.
- 휴장일 캘린더는 초기 MVP에서 반영하지 않고, 주중 정규장 시간 기준으로만 판단한다.
- GitHub Actions cron은 지연될 수 있으므로 화면에는 `generated_at`을 명확히 보여준다.
- 종목 상세 페이지는 1분마다 현재 종목 JSON을 cache-bust fetch하고, `generated_at` 또는 quote 값이 바뀌면 화면을 갱신한다.
- 수동 새로고침 버튼은 초기 MVP에서 노출하지 않는다.

나중 FastAPI:

- 서버는 종목별 quote를 짧은 TTL로 캐시한다.
- 화면 진입 시 캐시가 유효하면 캐시를 반환한다.
- 캐시가 만료되었으면 서버가 새로 조회한 뒤 반환한다.
- 사용자가 새로고침 버튼을 누르면 `POST /api/stocks/{ticker}/refresh`를 호출한다.
- 같은 ticker refresh가 이미 진행 중이면 기존 작업 결과를 기다리거나 현재 캐시와 `refreshing: true` 상태를 반환한다.

## Frontend 계획

React 라우트:

- `/`
- `/stocks/:ticker`

프론트엔드 데이터 client:

```text
src/dataClient/
  types.ts
  staticStockDataClient.ts
  fastApiStockDataClient.ts
  stockDataClient.ts
```

초기에는 `staticStockDataClient`만 사용한다. 나중에 환경 변수로 `fastApiStockDataClient`를 선택할 수 있게 한다.

주요 컴포넌트:

- `MarketIndexBoard`
- `StockSearch`
- `StockHeader`
- `QuoteSummary`
- `RefreshButton` (FastAPI 확장 시 사용)
- `PeerGroupSection`
- `PeerCompanyRow`
- `SourceMeta`
- `LoadingSpinner`
- `ErrorNotice`

PC 디자인 방향:

- 정보 밀도가 높은 투자 대시보드 느낌
- 큰 hero보다는 상단 요약 + 표 중심
- 상승/하락 색상은 명확하되 과하게 화려하지 않게
- peer 그룹은 카드형 섹션 안에 정렬된 테이블로 표시
- 기업명은 링크처럼 보이게 하고 클릭하면 같은 상세 화면으로 이동

## GitHub Actions 계획

### `refresh-data.yml`

역할:

- 5분마다 실행
- Python 의존성 설치
- `scripts/generate_static_data.py --skip-write-when-no-fetch` 실행
- `frontend/public/data` 갱신
- 변경된 JSON을 repository에 commit하고 Pages artifact에 포함

스케줄 초안:

```yaml
on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:
```

GitHub Actions scheduled workflow의 최단 주기는 5분이다. 실제 생성 시각은 지연될 수 있으므로 `generated_at`을 화면에 표시한다. 스크립트가 열린 시장을 찾지 못하고 모든 quote를 재사용한 경우에는 JSON 쓰기를 건너뛰어 불필요한 배포를 줄인다.

### `build-site.yml`

역할:

- React build
- GitHub Pages 배포

초기에는 data refresh와 build/deploy를 같은 workflow로 묶어도 된다. workflow가 복잡해지면 분리한다.

## FastAPI 확장 설계

초기에는 구현하지 않지만, 아래 API를 목표 계약으로 둔다.

```text
GET  /api/health
GET  /api/stocks
GET  /api/stocks/{ticker}
GET  /api/stocks/{ticker}/summary
POST /api/stocks/{ticker}/refresh
```

`GET /api/stocks/{ticker}/summary` 응답은 정적 JSON의 `stocks/{ticker}.json`과 같은 모양을 목표로 한다.

FastAPI가 필요해지는 시점:

- 새로고침 버튼이 진짜 외부 가격 소스에 즉시 요청해야 할 때
- CORS 문제 없이 외부 시세 endpoint를 서버에서 안정적으로 호출해야 할 때
- 사용자별 관심 종목 저장이 필요할 때
- 시가총액/순위/검색 인덱스처럼 서버 정규화가 필요한 데이터가 늘어날 때
- quote 히스토리 저장이 필요할 때

## 구현 단계

### Phase 1. 정적 데이터 구조

- `data/seed/peer_alerts` 생성
- 텔레그램 봇의 `config/peer_alerts/*.json`를 seed로 복사
- `scripts/generate_static_data.py` 뼈대 생성
- `frontend/public/data/index.json` 샘플 생성
- `frontend/public/data/stocks/*.json` 샘플 생성

### Phase 2. 프론트엔드 뼈대

- Vite React TypeScript 프로젝트 생성
- `/`, `/stocks/:ticker` 라우팅
- 정적 JSON fetch client 구현
- 데이터 로딩/에러 상태 구현

### Phase 3. 종목 상세 화면

- 현재 종목 정보 표시
- 가격 요약 표시
- peer 그룹별 테이블 표시
- peer 기업명 클릭 시 해당 ticker 상세 페이지 이동
- 초기에는 수동 새로고침 버튼을 숨김

### Phase 4. GitHub Actions 데이터 재생성

- 5분마다 Python 스크립트 실행
- 열린 시장만 가격 조회
- 닫힌 시장은 기존 quote 재사용
- quote 수집 로직 연결
- generated JSON 갱신
- GitHub Pages 배포까지 연결

### Phase 5. 메인 화면 뼈대

- 지수 카드 영역 UI 구현
- 관심 종목 링크 표시
- 실제 지수 데이터 연동은 이후 단계로 보류

### Phase 6. FastAPI 준비 폴더

- `backend/README.md` 작성
- 정적 JSON과 동일한 API 계약 문서화
- 실제 FastAPI 구현은 이후 단계로 보류

## 나중에 구현할 항목

- FastAPI 실시간 refresh
- 시가총액
- 시가총액 순위
- 시장 지수 실시간/지연 데이터
- 모바일 최적화
- 종목 검색 자동완성
- 가격 차트
- peer 변동률 랭킹
- 장 마감 시간별 데이터 freshness 표시
- 관심 종목 즐겨찾기
- 사용자별 설정
- quote 히스토리 저장

## 주요 리스크

- GitHub Actions cron은 정확히 5분마다 실행된다는 보장이 없다.
- 휴장일 캘린더를 반영하지 않으면 공휴일에도 정규장 시간에는 조회를 시도할 수 있다.
- Yahoo Finance, Naver Finance 등 비공식 endpoint는 응답 구조가 바뀔 수 있다.
- GitHub Actions에서 외부 시세 사이트 요청이 차단될 수 있다.
- 미국장은 서머타임 때문에 장마감 기준 시간이 계절별로 달라진다.
- 같은 기업이 여러 peer 그룹에 등장할 수 있으므로 ticker 기준 중복 처리가 필요하다.
- 정적 JSON 방식은 사용자의 즉시 가격 갱신 요구를 만족하지 못한다.

## 첫 구현 시 결정할 것

- GitHub Pages를 우선 배포 대상으로 확정할지
- `refresh-data`와 `build-site` workflow를 합칠지 분리할지
- quote fetch 코드를 텔레그램 봇에서 복사할지, 공용 모듈로 분리할지
- GitHub Actions가 생성한 JSON은 repository에 commit하고 Pages artifact에도 포함한다.
