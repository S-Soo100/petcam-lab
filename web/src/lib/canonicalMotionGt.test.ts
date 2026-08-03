import { describe, expect, it } from 'vitest';

import { canShowCanonicalCorrection, mapCanonicalMotionGt } from './canonicalMotionGt';

const GT = { primary_action: 'moving' };

describe('mapCanonicalMotionGt', () => {
  it('final 원장을 공개 계약과 한글 출처로 매핑한다', () => {
    expect(mapCanonicalMotionGt({
      status: 'final', revision_id: '11111111-1111-4111-8111-111111111111',
      decision: 'label', gt: GT, source_type: 'blind_consensus',
      updated_at: '2026-08-04T00:00:00Z', secret: 'hidden',
    })).toEqual({
      status: 'final', revisionId: '11111111-1111-4111-8111-111111111111',
      decision: 'label', gt: GT, source: 'blind_consensus', sourceLabel: '교차검수 합의',
      updatedAt: '2026-08-04T00:00:00Z', candidates: null,
    });
  });

  it('awaiting은 GT나 후보를 노출하지 않는다', () => {
    expect(mapCanonicalMotionGt({ status: 'review_in_progress', gt: GT, candidates: [GT] })).toEqual({
      status: 'review_in_progress', revisionId: null, decision: null, gt: null,
      source: null, sourceLabel: null, updatedAt: null, candidates: null,
    });
  });

  it('pending reconciliation 후보는 reviewer 식별자 없이 allowlist만 노출한다', () => {
    const mapped = mapCanonicalMotionGt({
      status: 'conflict', updated_at: '2026-08-04T00:00:00Z',
      candidates: [{ source: 'consensus', decision: 'label', gt: GT,
        source_type: 'owner_adjudication', reviewer_id: 'secret' }],
    });
    expect(mapped.candidates).toEqual([{ source: 'consensus', decision: 'label', gt: GT,
      sourceType: 'owner_adjudication', sourceLabel: 'Owner 불일치 해결' }]);
    expect(JSON.stringify(mapped)).not.toContain('reviewer');
  });

  it('모르는 status/source는 fail loud 한다', () => {
    expect(() => mapCanonicalMotionGt({ status: 'mystery' })).toThrow('invalid_canonical_gt_status');
    expect(() => mapCanonicalMotionGt({ status: 'final', source_type: 'mystery' })).toThrow('invalid_canonical_gt_source');
  });
});

describe('canShowCanonicalCorrection', () => {
  it('legacy 화면은 유지하고 canonical read-only canary에서는 보정을 숨긴다', () => {
    expect(canShowCanonicalCorrection(undefined, false)).toBe(true);
    expect(canShowCanonicalCorrection({ status: 'final' } as never, false)).toBe(false);
    expect(canShowCanonicalCorrection({ status: 'final' } as never, true)).toBe(true);
  });
});
