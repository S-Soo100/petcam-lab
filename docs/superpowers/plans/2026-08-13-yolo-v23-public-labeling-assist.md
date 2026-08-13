# YOLO v2.3 Public Labeling Assist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 공개 라벨링 웹 `https://label.tera-ai.uk/gecko-detector`에서 Vercel 로그인 없이 Dataset v2.3 후보 bbox를 안전하게 보여준다.

**Architecture:** Vercel production에서 별도 `YOLO_LABELING_ASSIST_ENABLED` flag가 켜진 전용 infer route만 v2.3 worker를 선택한다. 모든 production 요청은 `@vercel/firewall`의 분산 IP rate limit을 먼저 통과하며, worker bearer token은 서버 환경에만 남는다. flag 또는 WAF가 준비되지 않으면 503으로 닫고 기존 Preview 및 v2.1 rollback worker는 유지한다.

**Tech Stack:** Next.js 14, TypeScript, Vitest, `@vercel/firewall@1.2.5`, Vercel WAF/CLI, FastAPI YOLO worker

## Global Constraints

- 모델은 `yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018`, checkpoint SHA-256은 `dbed3a2d8018a2eb6e4130de57d301414fcd6c9ba80aef8aafdaba55b19a6a34`, threshold는 `0.25`다.
- 허용 용도는 사용자가 업로드한 이미지·영상의 candidate bbox 표시뿐이다.
- GT 자동확정, 빈 이미지/게코 부재 판정, GME routing, R2 A/B 분류, 삭제, VLM skip, 행동명, 사건 묶기는 금지한다.
- DB/R2 schema/data mutation은 하지 않는다.
- recall은 `0.5888888888888889`이므로 detection 0개를 `게코 없음`으로 해석하거나 표시하지 않는다.
- 학습 원본, immutable v2.3 release, 기존 v2.1 worker를 수정하거나 덮어쓰지 않는다.
- production WAF는 IP별 5회/10분 fixed-window이고 worker의 process-global 30회/10분, concurrency 1을 유지한다.
- secret, bearer token, local model path를 source, client bundle, response, log에 출력하지 않는다.

---

## File Structure

- Create `web/src/lib/yoloVercelRateLimiter.ts`: Vercel WAF SDK 결과를 공통 `RateLimiter` 계약으로 변환하고 오류 시 fail-closed한다.
- Create `web/src/lib/yoloVercelRateLimiter.test.ts`: 허용, 429, SDK 오류의 단위 계약을 검증한다.
- Modify `web/src/lib/yoloDetectionServer.ts`: sync/async limiter를 모두 await하고 WAF unavailable을 503으로 변환한다.
- Modify `web/src/lib/yoloDetectionServer.test.ts`: production distributed limiter gate와 fail-closed 회귀를 검증한다.
- Modify `web/src/lib/yoloDemoRoute.ts`: production assist flag와 Vercel limiter를 provider selection에 연결한다.
- Modify `web/src/app/api/yolo-demo/infer/route.test.ts`: production flag/url/token/WAF matrix를 검증한다.
- Modify `web/src/app/gecko-detector/page.tsx`: Preview와 public production이 같은 assist-enabled 판정을 쓰게 한다.
- Modify `web/src/app/gecko-detector/page.test.tsx`: public production copy와 flag-off fake copy를 검증한다.
- Modify `web/src/app/gecko-detector/_detector-demo.tsx`: `previewEnabled` prop/copy를 환경 중립적인 `assistEnabled`로 바꾼다.
- Modify `web/src/app/gecko-detector/_detector-demo.test.tsx`: 공개 assist processing/warning 회귀를 검증한다.
- Modify `web/package.json`, `web/package-lock.json`: `@vercel/firewall@1.2.5`를 고정한다.
- Modify `docs/superpowers/specs/2026-08-13-yolo-v23-public-labeling-assist-design.md`: 검증 증거와 최종 상태를 기록한다.

### Task 1: Vercel 분산 limiter adapter

**Files:**
- Create: `web/src/lib/yoloVercelRateLimiter.ts`
- Create: `web/src/lib/yoloVercelRateLimiter.test.ts`
- Modify: `web/src/lib/yoloDetectionServer.ts`
- Modify: `web/src/lib/yoloDetectionServer.test.ts`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`

**Interfaces:**
- Consumes: `checkRateLimit(id, { request })` from `@vercel/firewall@1.2.5`
- Produces: `VercelWafRateLimiter implements RateLimiter`, `RateLimitCheck`, async-compatible `RateLimiter.consume(key, nowMs, request)`

- [ ] **Step 1: dependency를 lockfile에 추가한다**

Run:

```bash
cd web && npm install @vercel/firewall@1.2.5
```

Expected: `package.json`과 `package-lock.json`만 dependency 설치로 변경되고 install exit 0.

- [ ] **Step 2: 허용·제한·오류의 failing test를 작성한다**

`web/src/lib/yoloVercelRateLimiter.test.ts`에 injected check 함수를 사용해 다음을 검증한다.

```ts
it('WAF 허용을 공통 limiter 결과로 바꾼다', async () => {
  const check = vi.fn().mockResolvedValue({ rateLimited: false });
  const limiter = new VercelWafRateLimiter(check);
  await expect(limiter.consume('ignored', 0, new Request('https://label.tera-ai.uk')))
    .resolves.toEqual({ allowed: true, retryAfterSec: 0 });
});

it('WAF 제한과 SDK 오류를 각각 429/503 상태로 구분한다', async () => {
  const denied = new VercelWafRateLimiter(vi.fn().mockResolvedValue({ rateLimited: true }));
  await expect(denied.consume('ignored', 0, new Request('https://label.tera-ai.uk')))
    .resolves.toEqual({ allowed: false, retryAfterSec: 600 });
  const failed = new VercelWafRateLimiter(vi.fn().mockRejectedValue(new Error('offline')));
  await expect(failed.consume('ignored', 0, new Request('https://label.tera-ai.uk')))
    .resolves.toEqual({ allowed: false, retryAfterSec: 0, unavailable: true });
});
```

`web/src/lib/yoloDetectionServer.test.ts`에는 `scope: 'distributed'` async limiter가 `unavailable: true`를
반환할 때 provider 호출 없이 503이 되는 test를 추가한다.

- [ ] **Step 3: test가 RED인지 확인한다**

Run:

```bash
cd web && npm test -- src/lib/yoloVercelRateLimiter.test.ts src/lib/yoloDetectionServer.test.ts
```

Expected: `yoloVercelRateLimiter` module 또는 async limiter 계약 부재로 FAIL.

- [ ] **Step 4: 최소 adapter와 async handler를 구현한다**

`RateLimitResult`에 `unavailable?: boolean`을 추가하고 `RateLimiter.consume`은 다음 반환형을 갖게 한다.

```ts
consume(key: string, nowMs: number, request: Request): RateLimitResult | Promise<RateLimitResult>;
```

handler는 `await deps.limiter.consume(requesterKey(request, deps.environment), deps.now().getTime(), request)`하고
`unavailable`이면 다음 응답을 반환한다.

```ts
return json({ detail: '연구 추론기가 준비되지 않았어.' }, 503);
```

새 adapter는 fixed ID와 fail-closed를 유지한다.

```ts
export const YOLO_RATE_LIMIT_ID = 'yolo-labeling-assist-ip';
export type RateLimitCheck = typeof checkRateLimit;

export class VercelWafRateLimiter implements RateLimiter {
  readonly scope = 'distributed' as const;
  constructor(private readonly check: RateLimitCheck = checkRateLimit) {}
  async consume(_key: string, _nowMs: number, request: Request): Promise<RateLimitResult> {
    try {
      const { rateLimited } = await this.check(YOLO_RATE_LIMIT_ID, { request });
      return rateLimited
        ? { allowed: false, retryAfterSec: 600 }
        : { allowed: true, retryAfterSec: 0 };
    } catch {
      return { allowed: false, retryAfterSec: 0, unavailable: true };
    }
  }
}
```

- [ ] **Step 5: focused test를 GREEN으로 만든다**

Run:

```bash
cd web && npm test -- src/lib/yoloVercelRateLimiter.test.ts src/lib/yoloDetectionServer.test.ts
```

Expected: 두 test file 모두 PASS.

- [ ] **Step 6: Task 1을 commit한다**

```bash
git add web/package.json web/package-lock.json web/src/lib/yoloDetectionServer.ts web/src/lib/yoloDetectionServer.test.ts web/src/lib/yoloVercelRateLimiter.ts web/src/lib/yoloVercelRateLimiter.test.ts
git commit -m "feat: YOLO 공개 추론 분산 rate limit 추가"
```

### Task 2: 명시적 production assist flag와 UI

**Files:**
- Modify: `web/src/lib/yoloDemoRoute.ts`
- Modify: `web/src/app/api/yolo-demo/infer/route.test.ts`
- Modify: `web/src/app/gecko-detector/page.tsx`
- Modify: `web/src/app/gecko-detector/page.test.tsx`
- Modify: `web/src/app/gecko-detector/_detector-demo.tsx`
- Modify: `web/src/app/gecko-detector/_detector-demo.test.tsx`

**Interfaces:**
- Consumes: `VercelWafRateLimiter`, `RateLimitCheck`, existing `HttpGeckoDetectionProvider`
- Produces: `labelingAssistEnabled(env): boolean`, `createPostFromEnv(env, fetchImpl, rateLimitCheck)`, `DetectorDemo({ assistEnabled })`

- [ ] **Step 1: production flag matrix failing test를 작성한다**

`route.test.ts`에서 기존 production hard-503 test를 다음 네 계약으로 확장한다.

```ts
it('production은 별도 assist flag가 없으면 worker env가 있어도 503이다', async () => {
  const workerFetch = vi.fn();
  const post = createPostFromEnv(productionEnv({ YOLO_LABELING_ASSIST_ENABLED: undefined }), workerFetch);
  expect((await post(uploadRequest())).status).toBe(503);
  expect(workerFetch).not.toHaveBeenCalled();
});

it('production assist는 URL/token이 하나라도 없으면 503이다', async () => {
  const workerFetch = vi.fn();
  const post = createPostFromEnv(productionEnv({ YOLO_WORKER_TOKEN: undefined }), workerFetch);
  expect((await post(uploadRequest())).status).toBe(503);
  expect(workerFetch).not.toHaveBeenCalled();
});

it('production assist는 WAF 제한이면 429이고 worker를 호출하지 않는다', async () => {
  const workerFetch = vi.fn();
  const wafCheck = vi.fn().mockResolvedValue({ rateLimited: true });
  const post = createPostFromEnv(productionEnv(), workerFetch, wafCheck);
  expect((await post(uploadRequest())).status).toBe(429);
  expect(workerFetch).not.toHaveBeenCalled();
});

it('production assist는 WAF 허용 뒤에만 worker를 호출한다', async () => {
  const workerFetch = workerResponseFetch();
  const wafCheck = vi.fn().mockResolvedValue({ rateLimited: false });
  const post = createPostFromEnv(productionEnv(), workerFetch, wafCheck);
  expect((await post(uploadRequest())).status).toBe(200);
  expect(workerFetch).toHaveBeenCalledOnce();
});
```

환경은 아래 exact keys를 사용한다.

```ts
{
  VERCEL_ENV: 'production',
  YOLO_LABELING_ASSIST_ENABLED: 'true',
  YOLO_WORKER_URL: 'https://yolo-v23-preview.example.test',
  YOLO_WORKER_TOKEN: 's'.repeat(43),
}
```

같은 test file에 다음 helper를 정의한다.

```ts
function productionEnv(overrides: Record<string, string | undefined> = {}) {
  return {
    VERCEL_ENV: 'production',
    NODE_ENV: 'production',
    YOLO_LABELING_ASSIST_ENABLED: 'true',
    YOLO_WORKER_URL: 'https://yolo-v23-preview.example.test',
    YOLO_WORKER_TOKEN: 's'.repeat(43),
    ...overrides,
  };
}

function workerResponseFetch() {
  return vi.fn(async (_url: string | URL | Request, init?: RequestInit) => Response.json({
    request_id: (init?.headers as Record<string, string>)['X-Request-Id'],
    media_kind: 'image',
    model_version: 'yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018',
    provider_mode: 'worker',
    processed_at: '2026-08-13T08:00:00.000Z',
    warning: 'Development-only 후보이며 게코 부재 판정이 아니야.',
    frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
    threshold: 0.25,
    usage_scope: 'labeling_bbox_assist_only',
    contribution_status: 'not_requested',
  }));
}
```

`page.test.tsx`에는 production flag true일 때 `Development-only 라벨링 보조`가 보이고 false일 때 fake
설명이 보이는 test를 추가한다. detector demo test는 prop을 `assistEnabled`로 바꾸고 worker 전달 문구와
`박스가 없어도 게코가 없다는 뜻은 아니야` 경고를 확인한다.

- [ ] **Step 2: 새 test가 RED인지 확인한다**

Run:

```bash
cd web && npm test -- src/app/api/yolo-demo/infer/route.test.ts src/app/gecko-detector/page.test.tsx src/app/gecko-detector/_detector-demo.test.tsx
```

Expected: production provider 선택과 `assistEnabled` prop이 아직 없어 FAIL.

- [ ] **Step 3: provider/UI의 공통 enable 판정을 구현한다**

`yoloDemoRoute.ts`에 pure helper를 추가한다.

```ts
export function labelingAssistEnabled(env: RouteEnvironment): boolean {
  const target = deploymentTarget(env);
  return (target === 'preview' && env.YOLO_PREVIEW_ENABLED === 'true')
    || (target === 'production' && env.YOLO_LABELING_ASSIST_ENABLED === 'true');
}
```

production은 `VercelWafRateLimiter(rateLimitCheck)`를, 나머지 환경은 기존 in-memory limiter를 사용한다.
URL/token validation failure는 기존 fake provider와 production 503 gate로 닫는다. page는 같은 helper를
사용하고 `DetectorDemo assistEnabled={assistEnabled}`를 전달한다. client component의 prop과
`processingMessage` parameter도 `assistEnabled`로 바꾼다.

- [ ] **Step 4: focused test를 GREEN으로 만든다**

Run:

```bash
cd web && npm test -- src/app/api/yolo-demo/infer/route.test.ts src/app/gecko-detector/page.test.tsx src/app/gecko-detector/_detector-demo.test.tsx
```

Expected: 세 test file 모두 PASS, production flag-off fetch 0, WAF denied fetch 0.

- [ ] **Step 5: Web 전체 회귀를 실행한다**

Run:

```bash
cd web && npm test && npx tsc --noEmit && npm run build
```

Expected: Vitest 전체 PASS, TypeScript exit 0, Next production build exit 0.

- [ ] **Step 6: Task 2를 commit한다**

```bash
git add web/src/lib/yoloDemoRoute.ts web/src/app/api/yolo-demo/infer/route.test.ts web/src/app/gecko-detector/page.tsx web/src/app/gecko-detector/page.test.tsx web/src/app/gecko-detector/_detector-demo.tsx web/src/app/gecko-detector/_detector-demo.test.tsx
git commit -m "feat: 라벨링 웹 공개 YOLO 보조 활성화"
```

### Task 3: 전체 검증과 독립 검수

**Files:**
- Modify only if review finds a requirement defect; keep scope to Task 1/2 files.

**Interfaces:**
- Consumes: committed Task 1/2 implementation
- Produces: exact reviewed commit SHA ready for Vercel production

- [ ] **Step 1: fresh 전체 test를 실행한다**

```bash
uv run pytest -q
cd web && npm test && npx tsc --noEmit && npm run build
```

Expected: Python baseline 이상 PASS, Web 전체 PASS, typecheck/build exit 0.

- [ ] **Step 2: secret/경계 정적 감사를 실행한다**

```bash
git diff HEAD~2..HEAD --check
git diff HEAD~2..HEAD --stat
rg -n "YOLO_WORKER_TOKEN|YOLO_LABELING_ASSIST_ENABLED|labeling_bbox_assist_only|게코 없음" web/src docs/superpowers/specs/2026-08-13-yolo-v23-public-labeling-assist-design.md
```

Expected: token value 0, enable flag은 server-only selection에만 존재, absence warning 유지.

- [ ] **Step 3: Codex CLI 독립 read-only review를 실행한다**

```bash
codex exec "Review HEAD~2..HEAD for the approved YOLO v2.3 public labeling-assist design. Report only actionable correctness, security, privacy, rate-limit, rollback, and scope-boundary defects. Do not modify files." -s read-only
```

Expected: critical/high defect 0. 발견된 defect는 최대 3회 TDD 수정 loop 안에서 고치고 focused/full test를 다시 실행한다.

- [ ] **Step 4: branch를 push한다**

```bash
git push origin codex/yolo-v23-labeling-assist-worker
```

Expected: upstream과 HEAD가 같고 worktree가 clean.

### Task 4: Vercel WAF·production 배포·rollback canary

**Files:**
- Modify: `docs/superpowers/specs/2026-08-13-yolo-v23-public-labeling-assist-design.md`

**Interfaces:**
- Consumes: exact reviewed branch SHA, existing v2.3 worker hostname/token, Vercel project `petcam-lab`
- Produces: public `label.tera-ai.uk/gecko-detector`, verified WAF, rollback evidence, `DEPLOYED_VERIFIED_LABELING_ASSIST_ONLY`

- [ ] **Step 1: 현재 production과 worker identity를 read-only로 재확인한다**

```bash
vercel inspect https://label.tera-ai.uk
curl -fsS https://label.tera-ai.uk/gecko-detector -o /dev/null -w '%{http_code}\n'
curl -sS -X POST https://label.tera-ai.uk/api/yolo-demo/infer -o /dev/null -w '%{http_code}\n'
```

Expected: page 200, infer 503, 현재 production deployment ID와 rollback target 기록. Mac mini health는 full SHA와 threshold `0.25`가 일치해야 한다.

- [ ] **Step 2: WAF rule을 publish하고 active config를 read-back한다**

Vercel Firewall에 `@vercel/firewall` condition ID `yolo-labeling-assist-ip`, fixed window 10분, IP별 5회,
action 429 rule을 추가한다. publish 전에 현재 empty config version을 기록하고, publish 뒤 Firewall API로
active rule name, rate-limit ID, window, limit, action만 read-back한다. secret이나 project/team ID는 출력하지 않는다.

Expected: active rule 1개가 exact ID/5/600/429로 확인되고 기존 rule 삭제 0.

- [ ] **Step 3: production server env를 비밀 노출 없이 준비한다**

기존 branch-scoped Preview의 `YOLO_WORKER_URL`과 `YOLO_WORKER_TOKEN`을 mode 0600 temporary env file로 pull한
뒤 Vercel production에 같은 값을 stdin으로 add한다. `YOLO_LABELING_ASSIST_ENABLED`는 아직 설정하지 않는다.
temporary file은 explicit path를 확인한 뒤 삭제한다.

Expected: `vercel env ls production`에 URL/token이 보이지만 값은 stdout/log에 나오지 않는다.

- [ ] **Step 4: flag-off production을 배포해 fail-closed를 확인한다**

```bash
cd web && vercel --prod --yes
```

Expected: deployment READY, `label.tera-ai.uk/gecko-detector` 200, infer 503, worker request count 불변.

- [ ] **Step 5: flag를 추가하고 public deployment를 만든다**

`YOLO_LABELING_ASSIST_ENABLED=true`를 production에 add하고 exact reviewed SHA에서 다시 `vercel --prod --yes`로
배포한다.

Expected: deployment READY, public URL은 Vercel login/secret query 없이 200.

- [ ] **Step 6: 기능 canary를 먼저 실행한다**

기존 v2.3 Preview에서 사용한 development-only runtime smoke artifact로 이미지와 영상을 검증한다. 실제
미검출을 부재로 오해하지 않도록 zero-detection 문구는 Vitest의 empty-frame fixture와 배포된 client
bundle/UI 렌더 결과로 검증한다.

Expected:
- image/video 200, provider `worker`
- model version `yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018`
- threshold `0.25`
- zero detection copy가 `게코 없음 판정이 아니니 직접 확인해줘.`
- browser console error 0, token/path leak 0, worker temp residue 0

- [ ] **Step 7: WAF negative canary를 실행한다**

같은 public IP에서 malformed POST를 연속 호출해 남은 fixed-window quota를 소진한다. 마지막 요청은 Vercel
WAF의 429여야 하며, 전체 요청 전후 worker request count가 같아야 한다.

Expected: 429, worker request count delta 0, bearer/token response 0.

- [ ] **Step 8: 실제 rollback과 복귀를 검증한다**

production의 `YOLO_LABELING_ASSIST_ENABLED`를 `false`로 바꿔 재배포하고 infer 503/worker count delta 0을
확인한다. 다시 `true`로 바꿔 exact reviewed SHA를 재배포하고 page 200, model/worker health identity를
확인한다. WAF counter 때문에 최종 infer canary가 429면 active WAF rule과 직전 성공한 기능 canary를 증거로
사용하고 제한 window가 지난 뒤 200 follow-up을 확인한다.

- [ ] **Step 9: evidence와 상태를 문서화하고 commit/push한다**

설계 문서 상태를 `DEPLOYED_VERIFIED_LABELING_ASSIST_ONLY`로 바꾸고 deployment ID, code SHA, worker full SHA,
WAF rule identity, image/video/zero/429/rollback 결과를 기록한다. secret, local path, raw user media는 기록하지
않는다.

```bash
git add docs/superpowers/specs/2026-08-13-yolo-v23-public-labeling-assist-design.md
git commit -m "docs: YOLO 공개 라벨링 보조 배포 증거 기록"
git push origin codex/yolo-v23-labeling-assist-worker
```

Expected: clean worktree, upstream 0/0, 공개 기능과 rollback 증거가 같은 tracked history에 존재.

- [ ] **Step 10: Slack에 공개 완료를 공유한다**

기존 `#99-petcam-lab-auto` 채널에 public URL, exact code SHA, model short/full SHA, threshold `0.25`, WAF
5회/10분, image/video/zero/rollback canary, `labeling_bbox_assist_only`와 금지 경계를 한 번 공유한다. token,
worker URL의 credential, local path, raw media는 포함하지 않는다.

Expected: Slack message URL 1개를 최종 보고에 포함한다.
