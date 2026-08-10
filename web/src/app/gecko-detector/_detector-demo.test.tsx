import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DetectorDemo, selectDroppedFile } from './_detector-demo';

describe('DetectorDemo drag-and-drop', () => {
  it('단일 drop 파일만 기존 선택 경로로 전달한다', () => {
    const file = new File(
      [new Uint8Array([0xff, 0xd8, 0xff])],
      'gecko.jpg',
      { type: 'image/jpeg' },
    );

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
