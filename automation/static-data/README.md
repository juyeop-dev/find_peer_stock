# 정적 자료 분리 배포

`scripts/package_static_data.py`는 원본 공개 디렉터리를 변경하지 않고 표준 USTAR·내용 해시 색인을 생성한다. `scripts/prepare_hosting_release.py`는 모든 해시·복원·무료 한도를 다시 검사하고 별도 UI와 assets-only Wrangler 설정을 만든다. 두 명령은 수집·업로드·구독 신청을 하지 않는다. 기존 `prepare_deployment_2014.py`는 이번 구조 정비에 사용하지 않는다.

```powershell
python scripts/package_static_data.py --source PATH_TO_VERIFIED_DIST_DATA --output hosting-output/data
python scripts/prepare_hosting_release.py --release PATH_TO_RELEASE --output hosting-output/prepared --data-base-url https://YOUR_STATIC_HOST/ --base-path /find_peer_stock/ --compat-data PATH_TO_FROZEN_LEGACY_DIST_DATA
```

폴더 전체가 아니라 `active.json`의 `ready_directory`만 정적 호스트에 올린다. 설정에는 `main`, R2, KV, D1, 유료 기능이 없다. CORS·캐시는 `_headers`가 처리하며 Range를 요구하지 않는다. 기본 묶음은 2MiB, 큰 파일은 직접 저장하거나 조각으로 나눈다. 이전 release가 있으면 `--previous PATH_TO_PREVIOUS_RELEASE`로 참조 자산 한 버전을 함께 보존한다. 합산 파일 수 20,000개·파일당 25MiB를 넘으면 게시 포인터가 바뀌지 않는다.

`VITE_DATA_BASE_URL`을 HTTPS 주소로 지정한 `npm run build:ui`는 생성기 prebuild를 실행하지 않으며 공개 데이터 디렉터리를 UI에 복사하지 않는다. 기존 같은 출처 배포는 미지정 상태에서 계속 동작한다. 원본 갱신 API 주소는 `VITE_LIVE_API_URL`과 기존 기본값을 유지한다.

전환 시 `--compat-data`로 마지막 검증된 flat 자료를 Pages의 `/data/`에 동결 보존한다. 같은 배포본의 형제 `assets/` 디렉터리도 보존해 이전 화면의 지연 로딩을 유지한다. 다른 위치의 자산은 `--compat-ui`로 지정한다. 이전 화면을 열어 둔 사용자의 조회와 기존 자료 URL을 유지하기 위한 것이다. 복사 후 원본·검증된 inventory 해시를 대조하고 Pages 전체에 1,000,000,000바이트의 보수적 제한을 적용한다. 이후 연도는 별도 정적 호스트에만 추가하고 이 동결본을 늘리지 않는다. 미래 release에서 동결본을 재사용하려면 원래 보고서의 `--compat-inventory-sha256`을 전달한다. 기존 클라이언트 지원을 종료하기 전까지 UI-only 산출물만 운영에 올리지 않는다.

운영 CLI는 공개 범위 메타데이터에 연결된 완료 증빙 파일의 SHA256과 실제 검사 결과도 확인한다. 증빙은 `evidence.path`에서 읽거나 `--publication-proof`로 지정한다. 단순히 수집 설정·메타데이터의 시작 연도만 수정해 새 연도를 게시할 수 없다.

배포 전에는 이번 구성에 추가되는 유료 기능이 없는지 확인한다. 비용 증빙 v2는 assets-only·새 유료 구독 없음·공개 저장소·기본 runner·Pages 전용 아티팩트·기본 범위 안의 캐시와 추가 비용 0원 계산을 검증한다. 예시는 `cost-evidence.example.json`이며 확인 항목은 기본 false다. 준비 보고서의 `cost_checks.verified`가 false면 업로드하지 않는다. 정적 Assets 저장·요청은 Workers 요금제와 별개로 추가 요금이 없으므로 계정 전체 구독·지출 예산 조회 권한을 요구하지 않는다. 기존 계정의 Free 상태를 확인했다고 주장하지도 않는다. 비용 증빙은 실제 확인 시각과 근거를 기록하며 24시간 이내여야 한다. 계정 구독 확인에 기반한 v1 증빙도 계속 읽는다.

운영 순서:

1. 최신 main과 변경 소스를 비교한다. `scripts/export_refactor_review.py --output hosting-output/source --remote-repository OWNER/REPO`는 소스·기준 해시·3-way 결과만 별도 디렉터리에 저장한다. 충돌이 있거나 main이 바뀌면 통합 전에 재검토한다.
2. 현재 공개 중인 데이터 release를 로컬에 보존하고 새 패키지의 `--previous`로 전달한다. 최초 이전에는 기존 Pages artifact와 flat 자료를 보존한다.
3. 비용 증빙을 확인한 뒤 준비된 `wrangler.json` 하나를 사용해 자료를 먼저 게시한다. 새 저장소·구독·유료 상품을 생성하지 않는다. Wrangler는 검증한 버전을 사용한다.
4. `node scripts/verify-static-host.mjs https://HOST/ EXPECTED_REVISION index.json credit/index.json`으로 실제 revision·CORS·캐시·바이트 해시를 확인한다. 실제 브라우저에서도 정적 호스트 주소로 조회한다.
5. 확인된 데이터 주소를 가리키는 Pages 산출물만 게시한다. 같은 Actions job에서 데이터는 직접 정적 호스트로 보내며 1GB급 데이터 묶음을 Actions artifact에 추가 저장하지 않는다. Pages artifact는 필요한 최소 보존 기간으로 설정한다. 이전 정상 Pages artifact와 배포 URL·commit·데이터 revision을 롤백 기록에 남긴다.
6. 실제 종목·실적·달력·섹터·수급·신용·리플레이의 날짜·수치·통화와 API 허용 Origin을 확인하고, 이전 release 파일도 새 호스트에서 계속 열리는지 확인한다.

`build-site.yml`은 `STATIC_DATA_PAGES_ENABLED=true`에서 검증이 끝난 `frontend/dist/data`를 정적 호스트에 게시한다. 예약 실행과 외부 스케줄러는 데이터만 갱신한다. `main` 푸시와 수동 `publish_pages=true`는 정적 revision 검증을 마친 뒤 Pages UI도 게시한다. 같은 원본과 공개 범위라면 기존 revision을 사용한다. 전환 후 `deploy-prepared-snapshots.yml`은 건너뛴다.

Actions 설정에는 정적 주소 `STATIC_DATA_BASE_URL`, `STATIC_CLOUDFLARE_ACCOUNT_ID`, Cloudflare 시크릿 `CLOUDFLARE_STATIC_API_TOKEN`이 필요하다. UI 배포는 기존 Pages의 공개 파일만 담은 GitHub Release ZIP의 `STATIC_PAGES_COMPAT_URL`, `STATIC_PAGES_COMPAT_SHA256`과 `STATIC_PAGES_COMPAT_INVENTORY_SHA256`을 사용한다. 동결본의 ZIP과 추출 자료 해시가 일치해야 한다. 첫 전환이 실패하면 `STATIC_DATA_PAGES_ENABLED`를 `false`로 되돌려 기존 경로로 배포할 수 있다. `deploy-static-snapshots.yml.example`은 1회성 이전을 검토할 때 사용한 예제다.

공식 근거: [Workers 한도](https://developers.cloudflare.com/workers/platform/limits/), [정적 과금·Range](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/), [assets 설정](https://developers.cloudflare.com/workers/static-assets/binding/), [GitHub Actions 과금](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [Pages 한도](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
