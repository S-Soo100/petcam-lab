import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderToStaticMarkup } from 'react-dom/server';

import BlindReviewProgress from './_blind-review-progress';
import { SelectionCard } from '@/components/ui/SelectionControl';
import { BLIND_DECISION_COPY } from '@/lib/motionBlindReview';
import type { BlindWorkspace } from '@/lib/motionBlindReviewServer';
import Button from '@/components/ui/Button';
import type { OwnerSubmissionView } from '@/lib/motionBlindReviewApi';
import * as blindReviewView from './_blind-review-view';
import {
  BLIND_ONBOARDING_SENTENCES,
  OWNER_CONFLICT_TITLE,
  OWNER_DIFFERING_TITLE,
  OWNER_RESOLVE_LABELS,
  blindActivityDayHeader,
  blindEmptyStateMessage,
  blindLateAddedBadge,
  blindPreviousWorkCta,
  blindProgressLines,
  blindSubmitResultMessage,
  blindTodayTitle,
  ownerDifferingFieldLabels,
} from './_blind-review-view';

const labelingDir = dirname(fileURLToPath(import.meta.url));
const detailSource = readFileSync(
  join(labelingDir, '_blind-review-detail.tsx'),
  'utf8',
);

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

describe('progress (본인 집계만, 상대 진행 비노출 — 설계 §5.1)', () => {
  it('renders own count and group aggregate only, never partner progress', () => {
    const html = renderToStaticMarkup(<BlindReviewProgress workspace={ws()} />);
    expect(html).toContain('내 작업 34/100');
    expect(html).toContain('그룹 합의 22 · 불일치 4 · 비교 대기 74');
    // 상대 라벨러의 제출 여부·진행 순서는 오늘 작업 화면에 표시하지 않는다(설계 §5.1).
    expect(html).not.toContain('파트너');
    expect(html).not.toContain('peer');
    expect(html).not.toContain('상대 판정:');
  });

  it('blindProgressLines is a pure formatter without a partner line', () => {
    const lines = blindProgressLines(ws());
    expect(lines.own).toBe('내 작업 34/100');
    expect(lines).not.toHaveProperty('partner');
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

describe('오늘 작업 제목·완료·이전 활동일(설계 §5.1·§11)', () => {
  it('오늘 작업 제목은 가장 최근 닫힌 활동일 기준', () => {
    expect(blindTodayTitle('2026-07-22')).toBe('7월 22일 오늘 작업');
    expect(blindTodayTitle(null)).toBe('오늘 작업');
  });

  it('완료 문구와 이전 활동일 CTA', () => {
    const done = ws({ priority_activity_day: null, available_days: ['2026-07-20'] });
    expect(blindEmptyStateMessage(done)).toBe('오늘 할 라벨링을 모두 끝냈어.');
    expect(blindPreviousWorkCta(done)).toBe('이전 활동일 작업 보기');
    // 남은 과거 활동일이 없으면 CTA 없음.
    expect(blindPreviousWorkCta(ws({ available_days: [] }))).toBeNull();
  });
});

describe('empty states (설계 §9·§11)', () => {
  it('explains why the queue is empty and what to do next', () => {
    expect(blindEmptyStateMessage(ws({ group_id: null }))).toBe(
      '담당 카메라가 아직 배정되지 않았어. 관리자에게 문의해.',
    );
    expect(
      blindEmptyStateMessage(ws({ priority_activity_day: null })),
    ).toBe('오늘 할 라벨링을 모두 끝냈어.');
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

  it('formats each differing field as side-by-side human-readable A/B values', () => {
    const ownerDifferenceRows = (
      blindReviewView as unknown as {
        ownerDifferenceRows?: (
          fields: readonly string[],
          a: OwnerSubmissionView,
          b: OwnerSubmissionView,
          durationSec: number,
        ) => unknown;
      }
    ).ownerDifferenceRows;
    expect(typeof ownerDifferenceRows).toBe('function');

    const a: OwnerSubmissionView = {
      decision: 'label',
      reason_code: 'behavior_data',
      note: null,
      initial_gt: {
        target: 'glass',
        context_tags: [],
        highlight_recommendation: 'exclude',
        activity_intensity: null,
        segments: [{ action: 'moving', start_sec: 0, end_sec: 28 }],
      },
    };
    const b: OwnerSubmissionView = {
      decision: 'label',
      reason_code: 'behavior_data',
      note: null,
      initial_gt: {
        target: 'object',
        context_tags: ['ir', 'overexposure'],
        highlight_recommendation: 'include',
        activity_intensity: 'high',
        segments: [{ action: 'moving', start_sec: 1, end_sec: 19 }],
      },
    };

    expect(
      ownerDifferenceRows!(
        ['decision', 'target', 'context_tags', 'activity_intensity', 'highlight_recommendation', 'segments'],
        a,
        b,
        32.5,
      ),
    ).toEqual([
      { key: 'decision', label: '최종 판정(라벨/보류/제외)', aValue: '라벨링하기', bValue: '라벨링하기' },
      { key: 'target', label: '행동 대상', aValue: '유리/벽', bValue: '일반 사물 (장식물·은신처·나뭇가지 등)' },
      { key: 'context_tags', label: '촬영 환경', aValue: '해당 없음', bValue: '야간 IR, 과노출' },
      { key: 'activity_intensity', label: '활동 강도', aValue: '없음', bValue: '높음' },
      { key: 'highlight_recommendation', label: '하이라이트 여부', aValue: '제외', bValue: '포함' },
      {
        key: 'segments',
        label: '동작과 시간',
        aValue: '위치 이동 · 영상 시작부터 28.0초까지',
        bValue: '위치 이동 · 1.0초부터 19.0초까지',
      },
    ]);
  });

  it('never exposes an unknown differing field or raw enum', () => {
    const ownerDifferenceRows = (
      blindReviewView as unknown as {
        ownerDifferenceRows?: (
          fields: readonly string[],
          a: OwnerSubmissionView,
          b: OwnerSubmissionView,
          durationSec: number,
        ) => { label: string; aValue: string; bValue: string }[];
      }
    ).ownerDifferenceRows;
    expect(typeof ownerDifferenceRows).toBe('function');

    const malformed: OwnerSubmissionView = {
      decision: 'label',
      reason_code: 'behavior_data',
      note: null,
      initial_gt: { private_internal_field: 'secret_raw_enum' },
    };
    const [row] = ownerDifferenceRows!(['private_internal_field'], malformed, malformed, 30);
    expect(row).toEqual({ key: 'private_internal_field', label: '확인 필요', aValue: '확인 필요', bValue: '확인 필요' });
    expect(JSON.stringify(row)).not.toContain('secret_raw_enum');
  });
});

describe('submit result messages (상대 원문 노출 0, 설계 §4.2)', () => {
  it('maps status to the three approved messages', () => {
    expect(blindSubmitResultMessage({ status: 'awaiting_peer' })).toBe('저장 완료 · 상대 판정 대기 중');
    expect(blindSubmitResultMessage({ status: 'agreed' })).toBe('두 판정 일치');
    expect(blindSubmitResultMessage({ status: 'conflict' })).toBe('관리자 확인으로 보냈어');
  });
});

describe('detail-derived comparator draft isolation', () => {
  it('uses the detail comparator for draft scope/key and never the global v1 constant', () => {
    expect(detailSource).not.toContain('BLIND_COMPARATOR_VERSION');
    expect(detailSource).toContain('detail.comparator_version');
    expect(detailSource).toContain('draftScope.comparatorVersion');
  });

  it('does not add comparator version to the submit body', () => {
    const start = detailSource.indexOf('submitBlindReview({');
    expect(start).toBeGreaterThan(-1);
    const submitRegion = detailSource.slice(start, start + 500);
    expect(submitRegion).not.toContain('comparatorVersion');
    expect(submitRegion).not.toContain('comparator_version');
  });
});
