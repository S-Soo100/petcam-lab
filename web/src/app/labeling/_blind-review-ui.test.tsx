import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import BlindReviewProgress from './_blind-review-progress';
import { SelectionCard } from '@/components/ui/SelectionControl';
import { BLIND_DECISION_COPY } from '@/lib/motionBlindReview';
import type { BlindWorkspace } from '@/lib/motionBlindReviewServer';
import Button from '@/components/ui/Button';
import {
  BLIND_ONBOARDING_SENTENCES,
  OWNER_CONFLICT_TITLE,
  OWNER_DIFFERING_TITLE,
  OWNER_RESOLVE_LABELS,
  blindActivityDayHeader,
  blindEmptyStateMessage,
  blindLateAddedBadge,
  blindProgressLines,
  blindSubmitResultMessage,
  ownerDifferingFieldLabels,
} from './_blind-review-view';

function ws(overrides: Partial<BlindWorkspace> = {}): BlindWorkspace {
  return {
    group_id: 'g1',
    group_name: 'A그룹',
    priority_activity_day: '2026-07-22',
    oldest_unlocked_activity_day: '2026-07-22',
    available_days: ['2026-07-22'],
    clip_total: 100,
    own_submitted: 34,
    partner_submitted: 28,
    agreed_count: 22,
    conflict_count: 4,
    awaiting_count: 74,
    late_added_count: 0,
    members: [
      { display_name: '크랑이아빠', submitted_count: 34 },
      { display_name: '파트너', submitted_count: 28 },
    ],
    ...overrides,
  };
}

describe('onboarding copy (설계 §4.1)', () => {
  it('shows the three approved sentences', () => {
    expect(BLIND_ONBOARDING_SENTENCES).toContain('같은 영상을 두 사람이 따로 확인해.');
    expect(BLIND_ONBOARDING_SENTENCES).toContain('라벨러 화면에는 상대방의 답이 보이지 않아.');
    expect(BLIND_ONBOARDING_SENTENCES[2]).toContain('두 답이 같으면 자동 완료');
  });
});

describe('progress (aggregate only, no peer distribution)', () => {
  it('renders own/partner counts and group aggregate', () => {
    const html = renderToStaticMarkup(<BlindReviewProgress workspace={ws()} />);
    expect(html).toContain('내 작업 34/100');
    expect(html).toContain('파트너 28/100');
    expect(html).toContain('그룹 합의 22 · 불일치 4 · 비교 대기 74');
    // 상대 판정 원문·분포는 절대 노출하지 않는다(설계 §5.1).
    expect(html).not.toContain('peer');
    expect(html).not.toContain('상대 판정:');
    expect(html).not.toMatch(/파트너.*라벨|파트너.*보류|파트너.*제외/);
  });

  it('blindProgressLines is a pure formatter', () => {
    const lines = blindProgressLines(ws());
    expect(lines.own).toBe('내 작업 34/100');
    expect(lines.partner).toBe('파트너 28/100');
  });

  it('shows a late-added badge without revoking older days', () => {
    const html = renderToStaticMarkup(<BlindReviewProgress workspace={ws({ late_added_count: 3 })} />);
    expect(html).toContain('어제 추가 3건');
    expect(blindLateAddedBadge(ws({ late_added_count: 0 }))).toBeNull();
  });

  it('formats the activity-day header', () => {
    expect(blindActivityDayHeader('2026-07-22')).toBe('우선 작업: 7월 22일 07:00 ~ 7월 23일 07:00');
    expect(blindActivityDayHeader(null)).toBeNull();
  });
});

describe('empty states (설계 §9)', () => {
  it('explains why the queue is empty and what to do next', () => {
    expect(blindEmptyStateMessage(ws({ group_id: null }))).toBe(
      '담당 카메라가 아직 배정되지 않았어. 관리자에게 문의해.',
    );
    expect(
      blindEmptyStateMessage(ws({ priority_activity_day: null, awaiting_count: 0 })),
    ).toBe('어제 내 작업을 모두 끝냈어. 그 전날 작업을 시작할 수 있어.');
    expect(
      blindEmptyStateMessage(ws({ priority_activity_day: null, awaiting_count: 5 })),
    ).toBe('파트너 제출을 기다리는 중이야. 너는 과거 작업을 계속할 수 있어.');
    // 우선 활동일이 있으면 빈 상태 메시지 없음.
    expect(blindEmptyStateMessage(ws())).toBeNull();
  });
});

describe('decision cards (설계 §4.2)', () => {
  it('render label card unpressed with exclude copy available', () => {
    const html = renderToStaticMarkup(
      <SelectionCard
        pressed={false}
        tone="success"
        title={BLIND_DECISION_COPY.label.title}
        description={BLIND_DECISION_COPY.label.description}
        onClick={() => undefined}
      />,
    );
    expect(html).toContain('라벨링하기');
    expect(html).toContain('aria-pressed="false"');
    expect(BLIND_DECISION_COPY.exclude.description).toContain('게코가 없거나 촬영·재생 오류');
  });
});

describe('owner conflict review copy (설계 §4.5)', () => {
  it('exposes conflict + differing titles and three resolution actions', () => {
    expect(OWNER_CONFLICT_TITLE).toBe('불일치 검수');
    expect(OWNER_DIFFERING_TITLE).toBe('서로 다른 항목');
    expect(OWNER_RESOLVE_LABELS).toEqual({ a: 'A 판정 채택', b: 'B 판정 채택', new: '새 판정 저장' });
  });

  it('renders the three resolve buttons enabled', () => {
    for (const label of Object.values(OWNER_RESOLVE_LABELS)) {
      const html = renderToStaticMarkup(
        <Button variant="labelingPrimary" onClick={() => undefined}>{label}</Button>,
      );
      expect(html).toContain(label);
      expect(html).not.toContain('disabled=""');
    }
  });

  it('maps differing field names to human labels (no internal terms)', () => {
    const labels = ownerDifferingFieldLabels(['decision', 'primary_action', 'segments']);
    expect(labels).toContain('대표 행동');
    expect(labels).toContain('동작과 시간');
    expect(labels.join(',')).not.toContain('primary_action');
  });
});

describe('submit result messages (상대 원문 노출 0, 설계 §4.2)', () => {
  it('maps status to the three approved messages', () => {
    expect(blindSubmitResultMessage({ status: 'awaiting_peer' })).toBe('저장 완료 · 상대 판정 대기 중');
    expect(blindSubmitResultMessage({ status: 'agreed' })).toBe('두 판정 일치');
    expect(blindSubmitResultMessage({ status: 'conflict' })).toBe('관리자 확인으로 보냈어');
  });
});
