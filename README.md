# Stock Peer Site

특정 종목과 peer 기업들의 주가 정보를 비교해서 보는 정적 웹 사이트입니다.

1차 MVP는 FastAPI 없이 동작합니다.

- GitHub Actions가 5분마다 실행되고, 장이 열린 시장의 가격 JSON만 새로 조회합니다.
- React 프론트엔드는 `public/data/*.json`을 읽어서 화면을 그립니다.
- 종목 상세 페이지는 1분마다 해당 종목 JSON을 다시 확인하고, 데이터가 바뀌면 화면을 자동 갱신합니다.
- 장이 닫힌 시장은 외부 조회를 하지 않고 마지막으로 저장된 quote를 재사용합니다.
- 나중에 FastAPI를 붙일 수 있도록 JSON 응답 구조를 API 응답처럼 유지합니다.

## 로컬 데이터 생성

```powershell
python .\scripts\generate_static_data.py --no-fetch
```

실제 시세 조회까지 시도하려면 `--no-fetch`를 빼고 실행합니다. 이때 장이 열린 시장만 조회하고, 닫힌 시장은 기존 JSON의 quote를 재사용합니다.

```powershell
python .\scripts\generate_static_data.py
```

모든 ticker를 강제로 조회하려면:

```powershell
python .\scripts\generate_static_data.py --force-fetch
```

생성 결과:

```text
data/generated/
frontend/public/data/
```

## 프론트엔드 실행

Node.js와 npm 설치 후:

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

1. Python으로 열린 시장의 가격 JSON 생성
2. React 빌드
3. GitHub Pages artifact 업로드
4. GitHub Pages 배포

스케줄은 GitHub Actions가 허용하는 최단 주기인 5분입니다. 실제 실행 시각은 GitHub Actions 부하에 따라 지연되거나 일부 누락될 수 있으므로, 화면의 `generated_at`을 기준으로 최신성을 확인합니다.

수동으로 즉시 갱신하려면 Actions에서 `Build Stock Peer Site`를 `Run workflow`로 실행합니다. 장 마감 후에도 모든 ticker를 다시 조회하려면 `force_fetch`를 켭니다.

로컬에서 `data/generated`와 `frontend/public/data`를 직접 갱신해 `main`에 푸시해도 GitHub Pages 배포가 다시 실행됩니다.

GitHub Pages는 repository settings에서 `GitHub Actions` 배포 소스로 설정합니다.
