import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import type { OwnerSubmissionView } from '@/lib/motionBlindReviewApi';

const submissionA: OwnerSubmissionView = {
  decision: 'label',
  reason_code: 'behavior_data',
  note: null,
  initial_gt: {
    target: 'glass',
    context_tags: [],
    highlight_recommendation: 'exclude',
  },
};

const submissionB: OwnerSubmissionView = {
  decision: 'label',
  reason_code: 'behavior_data',
  note: null,
  initial_gt: {
    target: 'object',
    context_tags: ['ir'],
    highlight_recommendation: 'include',
  },
};

describe('OwnerConflictComparison', () => {
  it('shows the actual A/B value for every differing field without raw enums', async () => {
    const module = await import('./_owner-conflict-comparison').catch(() => null);
    expect(module).not.toBeNull();

    const html = renderToStaticMarkup(
      <module.OwnerConflictComparison
        fields={['target', 'context_tags', 'highlight_recommendation']}
        submissionA={submissionA}
        submissionB={submissionB}
        durationSec={33}
      />,
    );

    for (const text of [
      '서로 다른 항목',
      '행동 대상',
      'A 선택',
      '유리/벽',
      'B 선택',
      '일반 사물',
      '촬영 환경',
      '해당 없음',
      '야간 IR',
      '하이라이트 여부',
      '제외',
      '포함',
    ]) {
      expect(html).toContain(text);
    }
    for (const raw of ['target', 'context_tags', 'highlight_recommendation', '>glass<', '>object<', '>ir<']) {
      expect(html).not.toContain(raw);
    }
  });

  it('keeps equal visual weight and mobile-safe wrapping for A/B values', async () => {
    const module = await import('./_owner-conflict-comparison').catch(() => null);
    expect(module).not.toBeNull();

    const html = renderToStaticMarkup(
      <module.OwnerConflictComparison
        fields={['target']}
        submissionA={submissionA}
        submissionB={submissionB}
        durationSec={33}
      />,
    );
    expect(html).toContain('grid-cols-2');
    expect(html).toContain('min-w-0');
    expect(html).toContain('break-words');
  });
});
