# 연도·정적 자료 구조 정비 인수인계

**최신 상태 — 2026-11-19:** 사용자의 재개 요청과 기존 승인으로 Cloudflare 정적 자료 게시·운영 검증을 완료했다. 부모 작업공간의 `hosting_review/2026-11-17/STAGE5B_STATIC_RESULT.md`, `STATIC_DEPLOYMENT.json`을 먼저 읽는다. 116,689개 전체 패키지 무결성, 실제 호스트 23개/7.2MB 원본 해시·CORS·캐시·404, 실제 Chromium 교차 출처·gzip·메모리 캐시 검증이 통과했다. 기존 Pages/API/원격 소스·CI는 변경하지 않았다. 아래 사용자 게시 승인 대기는 과거 상태이며 같은 release를 재게시하지 않는다. 다음은 최신 자료·호환본 확인 후 기존 UI 연결·소스 통합·한 CI 경로 활성화·운영 화면 검증이다. 이번 정적 게시 승인을 Pages/API 변경으로 임의 확대하지 않는다.

2026-11-18 기준 로컬 구현·검증과 추가 비용 계산을 마쳤다. 현재 구성은 추가 월 0원 예상이며 계정 전체 구독·예산 권한을 요구하던 조건은 비용 증빙 v2로 수정했다. 실제 Cloudflare 업로드는 자동 승인 검토에서 실행 전 거절되어 사용자 게시 승인을 기다린다. 수집 시작 연도는 `config/history-policy.json`, 검증된 공개 범위는 별도의 `shared/published-history.json`이다. 기본 수집 시작은 2014년이며 공개 선택지는 완료 증빙에서 생성한다. 2013년 실제 수집이나 과거 원본 재수집은 실행하지 않았다.

1·2A·2B·3·4A·4B 구현과 로컬 5A·6 검증이 끝났다. Python 전체 353개, Node 전체 185개를 통과했다. TypeScript·Vite UI 빌드와 Worker 번들, 실제 Chromium 1440·390·320px, 두 출처 CORS·gzip·캐시·실패 시 값 보존을 확인했다. 실제 기존 배포 자료 116,689개/932,666,930바이트는 모두 USTAR 또는 직접 자산으로 복원해 일치했다. 별도로 JavaScript 독자도 23개/7,210,960바이트의 실제 자료를 원본과 비교했다.

모든 증빙과 정확한 절대 경로는 작업공간 부모의 `hosting_review/2026-11-17/PROGRESS.md`, `STAGE4_RESULT.md`, `STAGE5_RESULT.md`, `STAGE6_RESULT.md`에 있다. `NEXT_SESSION.md`가 가장 먼저 읽을 파일이다. 이 작업본의 기준 커밋은 `4cfa2aacec65104439447344438555be6b732937`이며 아직 미커밋이다. 원래 작업본을 초기화하거나 통째로 복사·커밋하지 않는다.

이어갈 순서:

1. 작업공간 부모의 `COST_CALCULATION.md`, `COST_EVIDENCE_V2.json`, `STATIC_DEPLOYMENT_BLOCKED.json`을 읽고 실제 게시 승인을 받는다. 정적 저장·요청은 추가 요금이 없으며 유료 상품·runner·비공개 전환 등을 추가하지 않는다. 계정 구독·과거 청구서는 미확인으로 유지한다. 자동 승인 검토의 게시 거절을 우회하지 않는다.
2. `scripts/export_refactor_review.py`로 현재 원격 main과 다시 비교한다. 산출물의 `inventory.json`에 기준·제안·원격 해시와 충돌이 기록된다. 검토 파일만 별도 폴더에 만들며 실제 checkout·원격을 수정하지 않는다.
3. `automation/static-data/README.md`에 따라 준비된 데이터와 UI를 검토한다. 제안한 정적 호스트 주소는 아직 게시되지 않았다. `cost-evidence.example.json`은 기본 미확인 상태다. 실제 확인 결과를 채워 `prepare_hosting_release.py`를 다시 실행한다.
4. 이전 정적 release 한 버전과 이전 flat 자료·UI 자산을 보존한다. 자료를 먼저 게시하고 `verify-static-host.mjs` 및 실제 브라우저로 검증한 뒤 UI를 게시한다. 기존 Pages URL·API Origin은 유지한다.
5. 새 CI 경로를 검증한 후 하나만 활성화한다. 기존 workflow에는 `STATIC_DATA_BASE_URL`이 설정되면 Pages 업로드·배포를 중단하는 조건이 있다. `.yml.example`은 비활성 상태의 최초 이전용 수동 workflow다. 일상 자동 게시 주기는 실제 계정 조건을 확인한 후 활성화한다. 설정만 먼저 켜서 기존 게시를 중단하지 않는다.

연도 확장 계획만 확인하는 명령:

```powershell
python scripts/run_history.py --year 2013
python scripts/run_history.py --year 2012
python scripts/run_history.py --year 2011
```

각각 20개 작업을 계획하고 공식 달력·승인된 원본이 없는 13개 작업을 차단한다. `--execute` 없이는 수집하지 않는다. 실제 확장은 해당 연도 공식 거래일·특별 개장·시장별 원본 제공 범위와 `config/history-sources.json`의 승인된 revision부터 확인해야 한다. 존재하지 않는 2013년 달력이나 원본을 2014년 파일 복사로 대신하지 않는다.

수집 작업은 범위별 상태·잠금·명령·해시·프로세스·종료 코드를 기록한다. 완료된 동일 요청은 재실행하지 않고, 실행 중 자식 프로세스가 있으면 잠금을 빼앗지 않는다. 과거 제공자가 지원하지 않는 기간은 제한을 유지한다. 통화나 조정 기준이 다른 가격은 합치지 않는다. 기존 스냅샷·원본 정밀도·관측 시각을 보존한다.

기술상 주의 사항:

- SHA256 manifest 정규화는 키를 직접 정렬해 직렬화한다. JavaScript 객체를 정렬한 뒤 `JSON.stringify`만 쓰면 숫자처럼 생긴 색인 키가 재정렬되어 실제 256개 색인에서 Python과 해시가 달라진다.
- 정적 호스트는 Range를 요구하지 않는다. 묶음 전체를 받아 검증하며 메모리 캐시는 기본 32MiB다. 실패·404·손상은 성공한 새 원본 시각으로 표시하지 않는다.
- Windows에서 공개 검토 산출물 디렉터리는 작업공간 권한을 상속한다. `mkdtemp`의 전용 ACL로 생성해 사용자와 샌드박스가 서로 읽지 못하게 만들지 않는다. Chromium 프로필 등 임시 사적 자료는 계속 전용 임시 디렉터리를 사용한다.
- 2014년 등 과거 증빙 스크립트는 역사적 계약이므로 일괄 연도 치환하지 않는다. 새 실행은 일반 명령과 명시적 요청을 사용한다.
