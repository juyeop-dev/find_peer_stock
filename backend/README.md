# Backend 확장 메모

초기 MVP에서는 FastAPI를 구현하지 않습니다.

프론트엔드는 정적 JSON을 읽지만, JSON 모양은 나중의 FastAPI 응답과 동일하게 유지합니다. FastAPI를 붙일 때 목표 API는 아래와 같습니다.

```text
GET  /api/health
GET  /api/stocks
GET  /api/stocks/{ticker}
GET  /api/stocks/{ticker}/summary
POST /api/stocks/{ticker}/refresh
```

`GET /api/stocks/{ticker}/summary`는 현재 `frontend/public/data/stocks/{ticker}.json`과 같은 구조를 반환하게 만듭니다.

FastAPI가 필요한 시점:

- 새로고침 버튼이 외부 가격 소스에 즉시 요청해야 할 때
- 서버 캐시가 필요할 때
- 시가총액, 순위, 검색 인덱스, 히스토리 저장이 필요할 때
