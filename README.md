# Stock Peer Site

특정 종목과 peer 기업들의 주가 정보를 비교해서 보는 정적 웹 사이트입니다.

`신고가 캘린더` 페이지(`/new-highs`)에서는 달력 날짜별 신고가 종목, 업종·테마별 사유와 기업 설명을 확인합니다. 한국은 코스피를 기본으로 표시하며 코스닥도 선택할 수 있습니다. 52주 신고가와 역대 신고가를 별도로 집계합니다. 과거 데이터와 예시 리포트는 포함하지 않았으므로 첫 자료를 등록하기 전에는 빈 상태로 표시됩니다.

1차 MVP는 FastAPI 없이 동작합니다.

- 외부 Cloudflare 예약 실행이 5분마다 GitHub Actions를 호출하고, 모든 ticker의 가격 JSON을 새로 조회합니다. 외부 예약 실행은 별도 계정·토큰을 등록하고 배포해야 활성화됩니다.
- 기존 GitHub Actions 예약 실행도 예비 수단으로 유지합니다. 예약식이 5분이어도 실제 실행 간격은 길어질 수 있습니다.
- React 프론트엔드는 `public/data/*.json`을 읽어서 화면을 그립니다.
- 메인·종목 상세·신고가 페이지는 1분마다 캐시 없이 JSON을 확인합니다. 다른 탭에서 돌아오거나 연결이 복구되면 바로 다시 확인합니다.
- 조회 실패 시 마지막 정상 가격과 원래 조회 시각을 보존하며, 화면에 이전 가격임을 표시합니다. 모든 시세 조회가 실패하면 배포를 중단해 이전 사이트를 유지합니다.
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

GitHub에서 자동 생성된 데이터는 로컬 파일에 자동으로 내려오지 않습니다. 저장소가 깨끗하면 `git pull --ff-only`로 받거나 위 수집 명령으로 갱신합니다. `npm run dev`만 실행하면 시세 수집은 시작되지 않습니다.

`generated_at`은 파일 생성 시각, `quote.fetched_at`은 마지막 성공한 가격 조회 시각, `quote.market_time`은 제공처가 알려 준 시세 기준 시각입니다. 재조회 실패 시 `status: "stale"`, `refresh_status: "error"`, `last_checked_at`으로 실패 상태와 시도를 기록합니다. 주말이나 휴장에는 이전 거래일 가격이 유지되는 것이 정상입니다. 화면의 `브라우저 확인`은 배포 파일을 읽은 시각이며 가격이 갱신됐다는 뜻은 아닙니다.

## 일별 신고가 자료 추가

신고가 원본은 시세 JSON과 별도로 누적합니다. 아래 경로에 시장별·날짜별 JSON 파일을 추가하면 됩니다. `date`는 해당 시장의 거래일이며 파일명과 일치해야 합니다.

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
      "reason": "이 기업의 신고가 사유",
      "description": "기업의 주요 사업 설명",
      "change_pct": null
    }
  ]
}
```

- `high_type`은 `52_week`(52주 신고가) 또는 `all_time`(역대 신고가)입니다. 두 조건에 모두 해당하면 **`all_time`으로 한 번만 등록**합니다. 따라서 52주 신고가 집계에는 역대 신고가를 중복 포함하지 않습니다.
- `ticker`, `name`, `exchange`, `category`, `high_type`, `reason`은 필수입니다. 같은 날짜·시장의 동일 ticker 중복을 허용하지 않습니다. 한국 티커는 코스피 `.KS`, 코스닥 `.KQ` 표기를 권장합니다.
- `category`로 예전 자료처럼 업종·테마를 묶습니다. 선택 항목인 `category_reasons`에 공통 사유를 쓰고, `reason`에는 개별 기업 사유를 씁니다. 공통 사유만 있는 종목은 같은 내용을 `reason`에도 넣습니다. `category_reasons`의 키는 실제 등록 종목의 `category`와 일치해야 합니다.
- `description`은 사업 내용, `reason`은 신고가 배경입니다. `description`, `summary`, `category_reasons`, `sources`, `change_pct`는 선택 항목입니다. `change_pct: 3.25`는 3.25%이며, 등락률 미확인 시 생략하거나 `null`로 둡니다.
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

`generate_static_data.py`의 정기 실행에도 신고가 생성이 포함되어 있습니다. 이 코드는 **신고가 종목이나 사유를 자동 조사하지 않습니다**. 매일 검증한 자료를 원본 JSON에 추가하고 배포하면 달력에 해당 날짜가 누적됩니다. 생성 파일을 직접 편집하지 말고 `data/new-highs/reports` 원본을 수정합니다.

프론트엔드의 `npm run dev`와 `npm run build`도 시작 전에 신고가 생성기를 실행합니다. 개발 서버 실행 중 원본 자료를 추가했다면 위 Python 명령을 다시 실행합니다. 열린 페이지에는 다음 자동 확인 때 반영됩니다.

시장·거래소는 `data/new-highs/markets.json`에서 관리합니다. 한국(`korea`), 미국(`us`), 중국(`china`), 대만(`taiwan`), 일본(`japan`), 유럽(`europe`)을 미리 설정했습니다. 자료가 없는 시장은 빈 상태로 표시됩니다. 새 시장은 `id`, 표시명 `label`, 유효한 IANA 기준 시간대 `timezone`, 기본 거래소 `default_exchange`, 거래소 목록 `exchanges`를 추가한 뒤 같은 형식으로 리포트를 등록합니다. `default_exchange`에는 등록된 거래소 ID 또는 전체 거래소를 뜻하는 `all`을 지정합니다. 한국은 `KOSPI`, 나머지 시장은 `all`이 기본값입니다. 유럽 거래소도 필요에 따라 목록을 확장할 수 있습니다.

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

## 배포

`.github/workflows/build-site.yml`은 아래 작업을 수행합니다.

1. Python으로 모든 ticker의 가격 JSON 생성
2. React 빌드
3. GitHub Pages artifact 업로드
4. GitHub Pages 배포

### PC와 무관한 5분 예약 실행

[외부 스케줄러 설치 안내](automation/refresh-scheduler/README.md)에 따라 Cloudflare Worker를 배포합니다. Worker가 5분마다 GitHub의 `workflow_dispatch`를 호출하므로 PC가 꺼져 있어도 작동합니다. 진행 중인 작업이 있으면 중복 호출을 건너뜁니다. 시세 조회와 Pages 배포에는 추가 시간이 필요하며, 외부 서비스의 지연까지 제거하는 실시간 보장은 아닙니다.

**비용 없이 운영하는 조건:** Cloudflare는 Workers Free 플랜을 사용합니다. 하루 288회 예약 실행을 무료 한도 내에서 처리하고, 실제 수집·빌드는 현재 공개 GitHub 저장소의 무료 표준 실행기에서 수행합니다. 유료 서버나 데이터베이스는 필요하지 않습니다. 자세한 무료 한도와 계정 확인 방법은 위 설치 안내에 있습니다.

GitHub 자체 예약은 `3,8,13,...,58`분에 실행하는 예비 경로입니다. 2026-09-12 조사 당시 이 설정에도 실제 최근 실행은 약 2~4시간 간격이었습니다. [GitHub 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)도 예약 실행 지연·누락 가능성을 명시합니다. 화면은 배포 데이터가 20분 넘게 갱신되지 않으면 지연 안내를 표시합니다.

수동으로 즉시 갱신하려면 Actions에서 `Build Stock Peer Site`를 `Run workflow`로 실행합니다. `force_fetch` 기본값은 `true`이며 `false`이면 기존 가격을 유지하고 사이트만 다시 만듭니다. 워크플로는 전체 수집 실패를 오류로 처리하고, 테스트와 빌드 통과 후에만 게시합니다. 생성 데이터 커밋이 원격 동시 변경으로 실패하더라도 정상 생성된 사이트의 배포는 진행합니다.

로컬에서 `data/generated`와 `frontend/public/data`를 직접 갱신해 `main`에 푸시해도 GitHub Pages 배포가 다시 실행됩니다.

GitHub Pages는 repository settings에서 `GitHub Actions` 배포 소스로 설정합니다.

외부 스케줄러 검증:

```powershell
node --test automation/refresh-scheduler/test/*.test.mjs
```
