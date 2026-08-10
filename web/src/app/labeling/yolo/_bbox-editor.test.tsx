import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { BboxEditor } from './_bbox-editor';
import type { BlindTask, HumanBox } from '@/lib/yoloContribution';

const task: BlindTask = {
  task_id: '11111111-1111-4111-8111-111111111111',
  media_kind: 'image',
  media_url: 'https://signed.example/gecko.jpg',
  frame_manifest: [{ frame_index: 0, timestamp_ms: 0 }],
  stage: 'revealed',
};
const boxes: HumanBox[] = [{
  frame_index: 0,
  bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
}];

describe('BboxEditor', () => {
  it('편집 surface와 선택 가능한 사람 box를 키보드 접근 가능하게 렌더한다', () => {
    const html = renderToStaticMarkup(<BboxEditor boxes={boxes} onChange={() => undefined} task={task} />);
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('aria-label="사람 박스 1 선택 및 이동"');
    expect(html).toContain('Delete/Backspace');
  });

  it('Owner read-only 화면은 편집·삭제 컨트롤을 숨긴다', () => {
    const html = renderToStaticMarkup(<BboxEditor ariaLabel="bbox 검수 대상" boxes={boxes} onChange={() => undefined} readOnly task={task} />);
    expect(html).toContain('aria-label="bbox 검수 대상"');
    expect(html).not.toContain('사람 박스 1 선택 및 이동');
    expect(html).not.toContain('>삭제<');
  });
});
