# GME negative audit 캘리브레이션 로컬 통합 검증 보고

## 판정

`LOCAL_INTEGRATION_VERIFIED`야. Tasks 1–7 implementation 기준점
`2c6183a3af022049208ece88ea6a977bf6e7466b`에서 전체 Python/web/TypeScript/direct Next build와
disposable PostgreSQL runtime probe를 fresh 실행했다. tracked implementation은 로컬에서 검증됐지만
독립 reviewer 검토 전이며, Preview migration/deploy/canary와 production availability dry-run은 아직
실행하지 않았다. 현재 production 사용자 경험과 DB/R2/service/model 상태는 바뀌지 않았다.

이 상태는 `IMPLEMENTED_UNVERIFIED`보다 높지만 실행 계약의 `REVIEWED_READY_FOR_INTEGRATION` 또는
`PREVIEW_READY`는 아니다. Preview·production, detector recall/FNR, 모델 채택·개선, Dataset 편입,
재학습을 주장하지 않는다.

## 시작 Git 상태

| 항목 | 실제 값 |
|---|---|
| execution repo | `/Users/baek/.codex/worktrees/gme-activity-handoff-refresh/petcam-lab` |
| implementation host | `BaekBook-Pro-14-M5.local` |
| branch | `codex/gme-negative-audit-calibration` |
| starting HEAD | `2c6183a3af022049208ece88ea6a977bf6e7466b` |
| upstream | 미설정(`fatal: no upstream configured for branch`) |
| starting tracked/untracked | 둘 다 0, clean |
| 작업 범위 | `docs/FEATURES.md`, `docs/DATABASE.md`, 이 보고서만 |

Task 1 시작점 `d26efcf` 대비 58-file diff를 Python/DB, web API, web UI, experiment docs 그룹으로
나눠 확인했다. implementation/test 파일은 이번 문서화 dispatch에서 수정하지 않았다.

## Fresh 전체 회귀와 build

| 명령 | 결과 |
|---|---|
| `uv run pytest -q` | `2355 passed, 5 skipped in 35.15s` |
| `cd web && npm test -- --run` | `120 passed` files, `1152 passed` tests |
| `cd web && npx tsc --noEmit` | exit 0 |
| `cd web && npx next build` | Next.js `14.2.35`, compile/type/page-data/static generation/build exit 0, static pages `34/34` |

`npx next build`는 repo wrapper나 hook 우회가 아니라 plan이 허용한 direct build다. build 과정에서
외부 배포, Preview 생성, DB/R2/service write는 수행하지 않았다.

## Disposable PostgreSQL probe

`uv run python scripts/run_gme_negative_audit_probe.py --backend local-postgres`를 실행했다. loopback의
`blind_probe_gme_negative_<16 lowercase hex>` 임시 DB만 생성했고 migration과 synthetic fixture를 실제
parse/apply한 뒤 rollback/drop했다.

```text
GME_NEGATIVE_AUDIT_SCHEMA_OK
GME_NEGATIVE_AUDIT_BLIND_OK
GME_NEGATIVE_AUDIT_APPEND_ONLY_OK
PROBE_RESIDUE=0
```

이 증거는 7개 원장의 RLS/grant, 공개 RPC projection, assignment·bbox·duplicate submit,
UPDATE/DELETE/TRUNCATE 차단과 임시 DB residue 0을 포함한다. Preview/production DB에는 연결하지 않았다.

## 문서·보안 self-review

TypeScript AST는 일반 라벨러의 queue/detail/media/status exact response key를 추출해
`stratum|gme_run_id|detector_identity|media_sha256|control` 교집합 0을 확인했다. Owner overview는 설계대로
Owner에게만 stratum/control을 보여 주지만 GME run/model, source/R2 key, media hash는 반환하지 않는다.

Web server AST가 확인한 DB RPC 호출은 아래 allowlist뿐이다.

```text
fn_get_gme_negative_audit_item
fn_list_gme_negative_audit_queue
fn_submit_gme_negative_audit
fn_append_gme_negative_audit_correction
fn_append_gme_negative_audit_adjudication
fn_append_gme_negative_audit_dataset_decision
```

Supabase `.from(...).insert/update/upsert/delete` direct mutation은 0이고 R2 mutation command도 0이다.
Owner byte proxy의 유일한 upstream fetch는 body 없는 GET이며, redirect를 거부하고 bounded Range를
검증한다. Python AST는 preflight R2 protocol이 `head_object|get_object`뿐이고 forbidden R2 mutation
call 0임을 확인했다. Python DB write allowlist와 callsite는 모두 별도 `import --apply`의
`fn_create_gme_negative_audit_batch` 하나뿐이다. bounded grep도 일반 라벨러 forbidden key, web direct
DB mutation chain, R2 mutation 이름이 각각 0건임을 확인했다.

## 기능·데이터 경계

- 일반 라벨러는 배정된 blind 영상과 진행률만 보고 네 verdict를 제출한다. `gecko_present`는 현재
  decode-ready 프레임의 timestamp와 normalized bbox 한 개가 필수다.
- 7개 DB 테이블은 batch, batch event, frozen item, submission, correction, Owner adjudication,
  Dataset decision을 분리한다. 모두 RLS ON이고 role 불문 mutation blocker로 append-only다.
- audit는 기존 GME run, 사람 GT, queue eligibility, 활동시간, VLM, 하이라이트를 UPDATE/DELETE하지 않고
  어떤 영상도 자동 제외하지 않는다.
- scorer는 random-negative prevalence와 positive-control 발견률을 분리한다. 이 표본 하나로 detector
  recall/FNR을 계산하거나 production detector 채택을 판정하지 않는다.

## 실행하지 않은 단계와 Owner gate

| 단계 | 상태 |
|---|---|
| Tasks 1–7 implementation | implementation 기준점 고정 |
| Task 8 local regression/build/DB probe/docs self-review | locally verified |
| 독립 code review | controller의 fresh reviewer dispatch pending |
| Preview migration/deploy/6-item canary | pending, 별도 Owner gate |
| production availability dry-run | pending, 별도 Owner gate |
| TEST-SHEET approval·manifest freeze | pending, 별도 Owner gate |
| production manifest import·150-item 사람 검수 | pending, 별도 Owner gate |
| Dataset 편입·재학습·checkpoint/model/labeling production 배포 | 이 작업 밖, 새 Decision Gate와 별도 승인 필요 |

이번 dispatch에서 live Supabase/R2 credential 사용, DB/R2/service write, migration/deploy, push/merge,
model/labeling deploy는 모두 0건이다. 다음 단계는 controller의 독립 review이며, Critical/Important finding이
생기면 별도 TDD fix round에서 implementation/test를 고친 뒤 전체 gate를 다시 실행해야 한다.
