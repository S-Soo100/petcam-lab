# YOLO Drag-and-Drop Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/gecko-detector`의 기존 단일 파일 선택을 접근 가능한 드래그앤드롭 drop zone으로 확장하고 production에 배포한다.

**Architecture:** 기존 `DetectorDemo`의 `selectFile`을 단일 검증 진입점으로 유지하고 React drag event는 파일 개수와 drag-active 시각 상태만 관리한다. 새 라이브러리·API·DB·R2 변경 없이 공개 UI 한 파일과 테스트 한 파일만 수정한다.

**Tech Stack:** Next.js 14, React 18, TypeScript, Vitest, Tailwind CSS, Vercel

## Global Constraints

- JPEG/PNG/WebP는 10 MiB 이하, MP4/WebM은 50 MiB 이하, 빈 파일은 거부한다.
- 여러 파일 drop은 어느 파일도 선택하지 않고 `한 번에 파일 하나만 올려줘.`를 표시한다.
- 클릭·키보드·모바일 파일 선택과 기존 학습 후보 동의 UI를 유지한다.
- API magic byte·multipart·rate limit과 production 503 fail-closed 계약을 변경하지 않는다.
- R2 write, DB migration, 실제 worker/checkpoint 연결을 하지 않는다.

---

### Task 1: 단일 파일 drop 계약과 drop zone UI

**Files:**
- Create: `web/src/app/gecko-detector/_detector-demo.test.tsx`
- Modify: `web/src/app/gecko-detector/_detector-demo.tsx`

**Interfaces:**
- Consumes: 기존 `selectFile(next: File | null)`의 형식·크기·빈 파일 검증과 object URL 갱신.
- Produces: `selectDroppedFile(files: ArrayLike<File>): { file: File | null; error: string | null }`와 drag-enabled `DetectorDemo`.

- [ ] **Step 1: drop 계약 RED 테스트 작성**

```tsx
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DetectorDemo, selectDroppedFile } from './_detector-demo';

describe('DetectorDemo drag-and-drop', () => {
  it('단일 drop 파일만 기존 선택 경로로 전달한다', () => {
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'gecko.jpg', { type: 'image/jpeg' });
    expect(selectDroppedFile([file])).toEqual({ file, error: null });
  });

  it('여러 파일 drop은 선택하지 않고 명확히 거부한다', () => {
    const first = new File(['a'], 'one.jpg', { type: 'image/jpeg' });
    const second = new File(['b'], 'two.jpg', { type: 'image/jpeg' });
    expect(selectDroppedFile([first, second])).toEqual({
      file: null,
      error: '한 번에 파일 하나만 올려줘.',
    });
  });

  it('접근 가능한 파일 입력과 drop 안내를 함께 렌더한다', () => {
    const html = renderToStaticMarkup(<DetectorDemo />);
    expect(html).toContain('사진·영상을 끌어 놓거나 파일 선택');
    expect(html).toContain('type="file"');
    expect(html).toContain('data-drop-zone="true"');
  });
});
```

- [ ] **Step 2: RED 확인**

Run:

```bash
cd web && npm test -- --run src/app/gecko-detector/_detector-demo.test.tsx
```

Expected: `selectDroppedFile` export와 drop zone 문구·속성이 없어 FAIL.

- [ ] **Step 3: 최소 drop helper와 drag handler 구현**

```tsx
export function selectDroppedFile(files: ArrayLike<File>) {
  if (files.length !== 1) return { file: null, error: '한 번에 파일 하나만 올려줘.' };
  return { file: files[0], error: null };
}

function handleDrop(event: DragEvent<HTMLLabelElement>) {
  event.preventDefault();
  setDragActive(false);
  const dropped = selectDroppedFile(event.dataTransfer.files);
  if (dropped.error) {
    selectFile(null);
    setStatus('error');
    setMessage(dropped.error);
    return;
  }
  selectFile(dropped.file);
}
```

drop zone `<label>`에는 `data-drop-zone="true"`, `onDragEnter`, `onDragOver`, `onDragLeave`, `onDrop`을 연결한다. `dragActive`일 때 zinc 기본색을 emerald 강조색으로 바꾸고 “여기에 놓아줘”를 표시한다. 실제 file input은 label 안에 유지한다.

- [ ] **Step 4: GREEN 확인**

Run:

```bash
cd web && npm test -- --run src/app/gecko-detector/_detector-demo.test.tsx
```

Expected: 3 tests PASS.

- [ ] **Step 5: 관련 YOLO UI 회귀 확인**

Run:

```bash
cd web && npm test -- --run src/app/gecko-detector src/lib/yoloDetection.test.ts src/lib/yoloDetectionServer.test.ts
```

Expected: 전부 PASS, warning/error 0.

- [ ] **Step 6: 구현 커밋**

```bash
git add web/src/app/gecko-detector/_detector-demo.tsx web/src/app/gecko-detector/_detector-demo.test.tsx
git commit -m "feat: YOLO 업로드 드래그앤드롭 추가"
```

### Task 2: 전체 검증·문서·production 배포

**Files:**
- Modify: `docs/superpowers/plans/2026-08-10-yolo-drag-drop-upload.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Consumes: Task 1의 drag-enabled `DetectorDemo`.
- Produces: 배포 증거와 worker gate가 분리된 최신 SOT.

- [ ] **Step 1: 전체 회귀와 production build 확인**

Run:

```bash
uv run pytest -q
cd web && npm test -- --run
cd web && npx tsc --noEmit
cd web && npm run build
git diff --check
```

Expected: Python/Web/TypeScript/Next build 모두 성공, whitespace error 0.

- [ ] **Step 2: SOT 상태 기록**

`specs/next-session.md` 최상단 YOLO 블록과 이 계획 체크박스에 drag-and-drop 구현, test count,
production deployment ID, `/gecko-detector` 200, inference 503 fail-closed를 기록한다. 실제 worker/checkpoint,
R2 write, DB migration이 없음을 유지한다.

- [ ] **Step 3: 문서 포함 최종 커밋과 push**

```bash
git add docs/superpowers/plans/2026-08-10-yolo-drag-drop-upload.md specs/next-session.md
git commit -m "docs: YOLO 드래그앤드롭 배포 기록"
git push -u origin codex/yolo-drag-drop-upload
```

- [ ] **Step 4: PR과 Vercel production 배포**

ready PR을 `main` 대상으로 만들고 Vercel check 성공 뒤 exact head SHA로 merge한다. production deployment가
`READY`인지 확인하고 필요하면 해당 READY deployment를 `label.tera-ai.uk` alias로 promote한다.

- [ ] **Step 5: production canary**

Run:

```bash
curl -sS -L -o /dev/null -w '%{http_code}\n' https://label.tera-ai.uk/gecko-detector
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://label.tera-ai.uk/api/yolo-demo/infer
```

Expected: public page `200`, worker 미연결 inference `503`.
