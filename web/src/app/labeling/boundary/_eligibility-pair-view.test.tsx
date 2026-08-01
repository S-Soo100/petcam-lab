import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import Button from '@/components/ui/Button';
import EligibilityPairView from './_eligibility-pair-view';

const pair = {
  pair_id: 'p1', ordinal: 1, gap_sec: 10, gap_bin: 'le30' as const,
  left: { clip_id: 'l', started_at: '2026-07-01T01:00:00Z', duration_sec: 30, camera_name: '1번' },
  right: { clip_id: 'r', started_at: '2026-07-01T01:01:00Z', duration_sec: 30, camera_name: '1번' },
};

function findElement(node: ReactNode, predicate: (element: ReactElement) => boolean): ReactElement | null {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findElement(child, predicate);
      if (found) return found;
    }
    return null;
  }
  if (!isValidElement(node)) return null;
  if (predicate(node)) return node;
  return findElement((node.props as { children?: ReactNode }).children, predicate);
}

describe('Owner 영상 자격 확인 화면', () => {
  it('자격 판정을 네 의미 영역으로 나누고 사건 판정은 숨긴다', () => {
    const html = renderToStaticMarkup(<EligibilityPairView
      pair={pair}
      urls={{ left: 'https://x/a', right: 'https://x/b' }}
      selected={null}
      submitting={false}
      onSelect={() => {}}
      onSubmit={() => {}}
    />);
    expect(html).toContain('1단계 · 영상 자격 확인');
    expect(html).toContain('두 영상 모두 유효');
    expect(html).toContain('게코가 안 보임');
    expect(html).toContain('A에 게코 없음');
    expect(html).toContain('B에 게코 없음');
    expect(html).toContain('둘 다 게코 없음');
    expect(html).toContain('실제 게코 활동 없음');
    expect(html).toContain('A에 실제 활동 없음');
    expect(html).toContain('B에 실제 활동 없음');
    expect(html).toContain('둘 다 실제 활동 없음');
    expect(html).toContain('영상 자체를 확인할 수 없음');
    expect(html).toContain('A 영상 확인 불가');
    expect(html).toContain('B 영상 확인 불가');
    expect(html).toContain('둘 다 영상 확인 불가');
    expect(html).not.toContain('촬영 오류 또는 화면 확인 불가');
    expect(html).toContain('게코가 보이는지, 실제로 움직이는지, 영상이 정상인지');
    expect(html).toContain('판단이 어렵다는 이유만으로 무효로 고르지는 마');
    expect(html).not.toContain('같은 사건');
    expect(html).not.toContain('다른 사건');
  });

  it.each([
    ['left_gecko_absent', 'A에 게코 없음'],
    ['right_gecko_absent', 'B에 게코 없음'],
    ['both_gecko_absent', '둘 다 게코 없음'],
    ['left_no_gecko_activity', 'A에 실제 활동 없음'],
    ['right_no_gecko_activity', 'B에 실제 활동 없음'],
    ['both_no_gecko_activity', '둘 다 실제 활동 없음'],
    ['left_capture_or_media_error', 'A 영상 확인 불가'],
    ['right_capture_or_media_error', 'B 영상 확인 불가'],
    ['both_capture_or_media_error', '둘 다 영상 확인 불가'],
  ])('%s decision을 정확한 버튼에 연결한다', (decision, label) => {
    const html = renderToStaticMarkup(<EligibilityPairView pair={pair} urls={null} selected={null}
      submitting={false} onSelect={() => {}} onSubmit={() => {}} />);
    expect(html).toContain(`data-decision="${decision}"`);
    expect(html).toMatch(new RegExp(`data-decision="${decision}"[^>]*>${label}<`));
  });

  it('선택과 최종 제출 callback을 분리한다', () => {
    const onSelect = vi.fn();
    const onSubmit = vi.fn();
    const tree = EligibilityPairView({
      pair, urls: null, selected: 'eligible', submitting: false, onSelect, onSubmit,
    });
    const submitButton = findElement(tree, (element) => element.type === Button);
    expect(submitButton).not.toBeNull();
    (submitButton?.props as { onClick: () => void }).onClick();
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
