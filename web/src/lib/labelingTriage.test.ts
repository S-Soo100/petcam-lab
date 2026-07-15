import { describe, expect, it } from 'vitest';

import { effectiveTriageState, triageReasonLabel } from './labelingTriage';

describe('effectiveTriageState — owner 결정이 시스템 제안보다 우선(설계 §5.2)', () => {
  it('triage row 없음 → 본 큐 유지', () => {
    expect(effectiveTriageState(null)).toBe('queue');
  });

  it('owner 결정 없음 + quarantine → 검토 필요(pending)', () => {
    expect(
      effectiveTriageState({ suggested_route: 'quarantine', owner_decision: null }),
    ).toBe('pending');
  });

  it('owner label 이 quarantine 제안을 이긴다', () => {
    expect(
      effectiveTriageState({ suggested_route: 'quarantine', owner_decision: 'label' }),
    ).toBe('labeled');
  });

  it('owner skip 은 label 제안이어도 라벨링 안 함', () => {
    expect(
      effectiveTriageState({ suggested_route: 'label', owner_decision: 'skip' }),
    ).toBe('skipped');
  });

  it('owner 결정 없음 + label → 본 큐 유지', () => {
    expect(
      effectiveTriageState({ suggested_route: 'label', owner_decision: null }),
    ).toBe('queue');
  });
});

describe('triageReasonLabel — 사전 정의 문구만 노출(설계 §7)', () => {
  it('gate_absent', () => {
    expect(triageReasonLabel('gate_absent')).toBe('게코가 보이지 않을 가능성이 높음');
  });
  it('gate_static', () => {
    expect(triageReasonLabel('gate_static')).toBe(
      '게코가 보이지만 움직임이 거의 없을 가능성이 높음',
    );
  });
  it('manual', () => {
    expect(triageReasonLabel('manual')).toBe('owner가 직접 검토 대상으로 보냄');
  });
});
