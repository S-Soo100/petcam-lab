import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { WheelInteractionFields, WheelSegmentEndHelp } from './_wheel-interaction-fields';
import type { InteractionType } from '@/lib/labelingV2';

function render(selected: InteractionType[]) {
  return renderToStaticMarkup(
    <WheelInteractionFields selected={selected} onToggle={() => undefined} />,
  );
}

describe('WheelInteractionFields', () => {
  it('asks ride → rotate → push as the primary questions', () => {
    const html = render([]);
    expect(html).toContain('게코가 쳇바퀴 위나 안에 올라가 있었어?');
    expect(html).toContain('쳇바퀴가 실제로 돌아갔어?');
    expect(html).toContain('게코가 밖에서 쳇바퀴를 밀거나 건드렸어?');
    const ride = html.indexOf('올라가 있었어');
    const rotate = html.indexOf('쳇바퀴가 실제로 돌아갔어?');
    const push = html.indexOf('밀거나 건드렸어?');
    expect(ride).toBeLessThan(rotate);
    expect(rotate).toBeLessThan(push);
  });

  it('hides secondary choices behind 다른 행동도 기록하기 by default', () => {
    const html = render([]);
    expect(html).toContain('다른 행동도 기록하기');
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('떠났다가 다시 돌아왔어?');
    expect(html).not.toContain('움직이는 쳇바퀴를 따라갔어?');
  });

  it('opens secondary automatically when a restored draft already has a secondary enum', () => {
    const html = render(['repeated_return']);
    expect(html).toContain('떠났다가 다시 돌아왔어?');
    // disclosure 버튼은 이미 펼쳐졌으니 숨긴다.
    expect(html).not.toContain('다른 행동도 기록하기');
  });

  it('renders a natural-language summary of the selection', () => {
    const html = render(['ride', 'rotate']);
    expect(html).toContain('선택한 내용:');
    expect(html).toContain('쳇바퀴 위·안에 올라감');
    expect(html).toContain('쳇바퀴를 실제로 돌림');
  });

  it('does not add a leave enum and keeps existing enum strings', () => {
    // 렌더 마크업에 저장 enum 문자열이 그대로 유지되는지(payload 불변)는 helper 계약으로 보장된다.
    // 여기서는 '떠남' 같은 새 enum 이 화면에 등장하지 않음을 확인한다.
    const html = render(['ride', 'push', 'rotate', 'chase', 'repeated_return', 'other']);
    expect(html).not.toContain('leave');
    expect(html).not.toContain('떠남');
  });
});

describe('WheelSegmentEndHelp', () => {
  it('contains both approved sentences', () => {
    const html = renderToStaticMarkup(<WheelSegmentEndHelp />);
    expect(html).toContain(
      '게코가 쳇바퀴에서 내려온 뒤 더 이상 쳇바퀴와 상호작용하지 않는 순간을 종료 시점으로 표시해.',
    );
    expect(html).toContain('내려온 뒤에도 밖에서 밀거나 건드리면 상호작용이 계속되는 중이야.');
  });
});
