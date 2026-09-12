# 외부 데이터 갱신 스케줄러

Cloudflare Worker가 PC와 관계없이 5분마다 `juyeop-dev/find_peer_stock`의 `main` 브랜치에 있는 `build-site.yml`을 실행합니다. Worker는 실행 요청만 보내며 실제 시세 수집·정적 데이터 생성·GitHub Pages 배포는 기존 Actions가 담당합니다. 저장소의 GitHub cron은 예비 경로로 유지합니다.

`queued`, `in_progress`, `waiting`, `pending`, `requested` 실행이 있으면 이번 요청을 건너뜁니다. 상태별 조회라 오래된 진행 중 실행이 최근 완료 실행에 가려지지 않습니다. 조회 실패 시에도 실행 요청을 보내지 않습니다. 이 조회는 원자적 잠금이 아니므로 동시에 발생하는 GitHub cron까지 완전히 중복 방지하지는 못하며 기존 워크플로의 `concurrency` 설정이 배포 겹침을 제어합니다. [GitHub 실행 조회 API](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow)

## 비용 없이 운영하는 조건

**Cloudflare Workers Free 플랜만 사용합니다.** 이 작업을 위해 유료 플랜에 가입하거나 결제정보를 추가할 필요는 없습니다. 로그인한 계정의 Workers 플랜이 Free인지 확인한 뒤 배포합니다.

- 5분 예약 실행은 하루 288회입니다. Workers Free의 하루 100,000회와 실행당 CPU 10ms 범위에서 동작하는 작은 HTTP 호출 스케줄러이며, 실제 수집과 빌드는 GitHub에서 수행합니다. 네트워크 응답 대기는 CPU 사용 시간에 포함되지 않습니다. 계정의 다른 Worker와 일일 한도를 공유합니다. [공식 요금](https://developers.cloudflare.com/workers/platform/pricing/)
- 무료 한도를 넘으면 실행이 제한됩니다. 무료 플랜 사용량 초과를 이유로 유료 플랜으로 자동 전환하는 구성은 아닙니다. [무료 한도](https://developers.cloudflare.com/workers/platform/limits/)
- 데이터베이스, 유료 서버, 사용자 도메인은 사용하지 않습니다. 기본 Worker 로그만 사용합니다.
- 현재 `find_peer_stock`은 공개 저장소이고 워크플로는 표준 `ubuntu-latest` 실행기를 사용하므로 GitHub Actions 실행은 무료입니다. GitHub Pages를 그대로 사용하며 아티팩트는 짧은 기본 보관 기간을 유지합니다. 저장소를 비공개로 바꾸거나 유료 실행기로 바꾸는 경우에는 이 조건을 다시 확인해야 합니다. [GitHub Actions 요금](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

위 내용은 2026-09-12 공식 문서 기준입니다. 무료 플랜의 실행 제한으로 갱신이 실패하면 다음 예약 실행에서 다시 시도하며, 비용을 지불하는 확장으로 전환하지 않습니다.

## 최초 설정

준비물:

- Workers Free 플랜을 사용하는 Cloudflare 계정과 해당 계정의 Worker 배포 권한.
- Node.js 22 이상과 npm. Windows 명령은 PowerShell의 npm 스크립트 실행 정책에 영향을 받지 않도록 `npx.cmd`를 사용합니다. macOS/Linux에서는 `npx`를 사용합니다. [Wrangler 설치 안내](https://developers.cloudflare.com/workers/wrangler/install-and-update/)
- GitHub 저장소에서 Actions와 Pages가 활성화되어 있고 `main`에 `workflow_dispatch`가 포함된 `build-site.yml`이 있어야 합니다.
- GitHub **fine-grained personal access token**: Resource owner `juyeop-dev`, Repository access는 **Only select repositories → find_peer_stock**, Repository permissions는 **Actions: Read and write**만 추가합니다. 자동 포함되는 Metadata 읽기를 제외한 Contents·Workflows 등의 추가 권한은 필요 없습니다. 만료일을 기록하고 만료 전에 교체합니다. [GitHub workflow dispatch 권한](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)

저장소 루트 `stock_peer_site`에서 실행합니다.

```powershell
Set-Location automation/refresh-scheduler
node --test
npx.cmd wrangler@4.131.1 login
npx.cmd wrangler@4.131.1 deploy --dry-run
npx.cmd wrangler@4.131.1 deploy
npx.cmd wrangler@4.131.1 secret put GITHUB_TOKEN
```

마지막 명령의 비공개 입력창에 GitHub 토큰을 입력합니다. 토큰을 채팅, 명령 인자, `wrangler.jsonc`, Git 추적 파일에 붙여 넣지 않습니다. 이 이름은 Worker의 비밀값 이름이며, GitHub Actions가 실행마다 제공하는 임시 `GITHUB_TOKEN`을 복사하는 방식이 아닙니다. `secret put`은 비밀값을 저장한 새 Worker 버전을 즉시 배포합니다. 최초 `deploy`부터 비밀값 등록 전까지 호출되면 `missing_github_token`으로 실패하며 GitHub에는 요청하지 않습니다. [Cloudflare Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)

계정이 여러 개라면 Wrangler가 제시하는 계정 중 사용할 계정을 선택합니다. 필요하면 `wrangler.jsonc`에 해당 Cloudflare `account_id`를 추가합니다. 설치를 생략하고 `npx`로 Wrangler를 실행하는 구성이며 Worker 자체의 실행 의존성은 없습니다.

## 가동 확인

```powershell
npx.cmd wrangler@4.131.1 tail
```

Cloudflare 대시보드의 Worker 설정에서 Cron Trigger `*/5 * * * *`가 있는지 확인합니다. Cron은 UTC 기준이며 변경 전파에 최대 15분이 걸릴 수 있습니다. [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)

로그의 `dispatched`는 GitHub가 실행 요청을 수락했다는 뜻입니다. [GitHub Actions 실행 목록](https://github.com/juyeop-dev/find_peer_stock/actions/workflows/build-site.yml)에서 `workflow_dispatch` 실행과 Pages 배포 성공을 확인하고 사이트의 데이터 갱신 시각이 바뀌었는지 확인합니다. `skipped`와 `active_workflow`는 앞선 실행이 끝나기를 기다리는 정상 상태입니다. 5분은 실행 요청 주기이며 실제 화면 반영에는 GitHub 실행 대기·수집·빌드·배포 시간이 추가됩니다.

오류 코드는 `missing_github_token`, `list_runs_http_401`, `dispatch_http_403`, `list_runs_timeout` 등의 형태입니다. 401은 토큰·만료 여부, 403은 저장소 선택·Actions 권한·API 제한을 확인합니다. 각 API 요청의 제한 시간은 10초입니다. 응답 본문과 원본 예외는 로그에 기록하지 않습니다. 불확실한 dispatch 결과를 같은 호출 안에서 재전송하지 않고 다음 cron에서 실행 상태부터 다시 확인합니다.

Worker는 `scheduled()`만 제공하며 `workers_dev`, `preview_urls`를 끄고 HTTP route를 설정하지 않았습니다. 공개 URL로 실행시키는 수동 엔드포인트는 없습니다. 수동 갱신은 GitHub Actions의 **Run workflow**를 사용합니다. [Wrangler 설정](https://developers.cloudflare.com/workers/wrangler/configuration/)

## 수정·비밀값 교체·중지

코드 또는 설정 변경 후 `node --test`와 `npx.cmd wrangler@4.131.1 deploy`를 실행합니다. 토큰 교체는 `npx.cmd wrangler@4.131.1 secret put GITHUB_TOKEN`을 다시 실행합니다. 중지는 `wrangler.jsonc`의 `triggers.crons`를 `[]`로 바꾼 뒤 배포합니다. GitHub의 예비 cron은 계속 유지됩니다.

이 디렉터리를 저장소에 추가하는 것만으로 Cloudflare가 자동 배포되지는 않습니다. 최초 로그인·Worker 배포·비밀값 등록·위 가동 확인까지 완료해야 외부 스케줄러가 동작합니다.
