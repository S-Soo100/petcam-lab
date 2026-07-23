import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { INTERACTION_TYPES } from '@/lib/labelingV2';
import {
  BLIND_COMPARATOR_VERSION,
  canonicalSubmissionPair,
  compareBlindSubmissions,
  type BlindSubmissionInput,
} from '@/lib/motionBlindReview';

// Task 7 교차 계층 하드닝 — 소스 정적 스캔 + 순수 불변식으로 설계 계약(§5.1·§4.6·§4.7)을 잠근다.
// 라우트/컴포넌트별 행동은 각 태스크 테스트가 이미 덮으므로, 여기서는 회귀 시 한눈에 잡히는
// 파일 단위 계약(검은 active 부재·HTML 주입 부재·enum 불변·비교기 결정성)을 고정한다.

const labelingDir = dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => readFileSync(join(labelingDir, rel), 'utf8');

// 블라인드 라벨러/owner 화면 파일 집합.
const BLIND_UI_FILES = [
  '_blind-review-detail.tsx',
  '_blind-review-queue.tsx',
  '_blind-review-progress.tsx',
  '_blind-review-onboarding.tsx',
  '_home-switch.tsx',
  'blind/[clipId]/page.tsx',
  'blind/canary/[cohortId]/page.tsx',
  'blind/canary/[cohortId]/[clipId]/page.tsx',
  'blind/conflicts/page.tsx',
  'blind/conflicts/[clipId]/page.tsx',
  'blind/groups/page.tsx',
];

describe('visual contract — no black active fill in blind screens (설계 §4.6)', () => {
  it('none of the blind screens use black active classes', () => {
    for (const f of BLIND_UI_FILES) {
      const src = read(f);
      expect(src, f).not.toContain('bg-zinc-900 text-white');
      expect(src, f).not.toContain('border-zinc-900 bg-zinc-900');
    }
  });
});

describe('security — no HTML injection surface (설계 §7)', () => {
  it('blind screens never use dangerouslySetInnerHTML (notes render as text)', () => {
    for (const f of BLIND_UI_FILES) {
      expect(read(f), f).not.toContain('dangerouslySetInnerHTML');
    }
  });
});

describe('payload immutability — interaction enums unchanged (설계 §4.7)', () => {
  it('the six interaction enums are exactly preserved', () => {
    expect([...INTERACTION_TYPES]).toEqual(['ride', 'push', 'rotate', 'chase', 'repeated_return', 'other']);
  });

  it('no leave enum is introduced', () => {
    expect(INTERACTION_TYPES as readonly string[]).not.toContain('leave');
  });
});

describe('blind draft wiring (하드닝 §5)', () => {
  const detail = read('_blind-review-detail.tsx');

  it('detail imports the shared blind draft helper (per-tab sessionStorage)', () => {
    expect(detail).toContain("from '@/lib/motionBlindDraft'");
    expect(detail).toContain('readBlindDraft');
    expect(detail).toContain('writeBlindDraft');
    expect(detail).toContain('clearBlindDraft');
  });

  it('the draft payload builder never serializes lease token, peer, VLM, evidence, or R2 key', () => {
    // 주석이 아니라 실제 writeBlindDraft(...) 호출 + payload 객체 영역을 검사한다.
    const start = detail.indexOf('writeBlindDraft(');
    expect(start).toBeGreaterThan(-1);
    const region = detail.slice(start, start + 900);
    for (const forbidden of ['leaseTokenRef', 'lease_token', 'peer_', 'vlm', 'evidence', 'r2_key']) {
      expect(region, forbidden).not.toContain(forbidden);
    }
  });
});

describe('comparator adversarial invariants (설계 §5.2·§5.3)', () => {
  function labelGt(overrides: Record<string, unknown> = {}): BlindSubmissionInput {
    return {
      decision: 'label',
      initial_gt: {
        visibility: 'visible',
        primary_action: 'moving',
        observed_actions: ['moving'],
        segments: [{ action: 'moving', start_sec: 0, end_sec: 1 }],
        target: 'none',
        human_confidence: 'certain',
        context_tags: [],
        activity_intensity: null,
        highlight_recommendation: 'exclude',
        enrichment_object: 'none',
        interaction_types: [],
        note: null,
        ...overrides,
      },
      note: null,
      reason_code: 'behavior_data',
    };
  }

  it('is symmetric for agree/conflict regardless of submit order (concurrency safety)', () => {
    const a = labelGt({ primary_action: 'moving' });
    const b = labelGt({ primary_action: 'drinking' });
    expect(compareBlindSubmissions(a, b).status).toBe('conflict');
    expect(compareBlindSubmissions(b, a).status).toBe('conflict');
    // canonical pairing gives both concurrent submitters the same (a,b) order.
    expect(canonicalSubmissionPair({ id: 'z', digest: 'd1' }, { id: 'a', digest: 'd2' })).toEqual([
      { id: 'a', digest: 'd2' },
      { id: 'z', digest: 'd1' },
    ]);
  });

  it('500ms boundary is exact and unordered arrays agree', () => {
    expect(
      compareBlindSubmissions(
        labelGt({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
        labelGt({ segments: [{ action: 'moving', start_sec: 1.5, end_sec: 2.5 }] }),
      ).status,
    ).toBe('agreed');
    expect(
      compareBlindSubmissions(
        labelGt({ segments: [{ action: 'moving', start_sec: 1, end_sec: 2 }] }),
        labelGt({ segments: [{ action: 'moving', start_sec: 1.501, end_sec: 2 }] }),
      ).status,
    ).toBe('conflict');
    expect(
      compareBlindSubmissions(
        labelGt({ observed_actions: ['moving', 'static', 'moving'] }),
        labelGt({ observed_actions: ['static', 'moving'] }),
      ).status,
    ).toBe('agreed');
  });

  it('an HTML-like note is compared as opaque text and never affects the result', () => {
    const a = labelGt({ note: '<script>alert(1)</script>' });
    const b = labelGt({ note: null });
    // note 는 비교에서 제외 → 동일 판정이면 여전히 agreed. 저장 원문은 보존된다.
    expect(compareBlindSubmissions(a, b).status).toBe('agreed');
    expect(compareBlindSubmissions(a, b).final_gt?.note).toBe('<script>alert(1)</script>');
  });

  it('comparator version is frozen', () => {
    expect(BLIND_COMPARATOR_VERSION).toBe('motion-blind-v1');
  });
});
