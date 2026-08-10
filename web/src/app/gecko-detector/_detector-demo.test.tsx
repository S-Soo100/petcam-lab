// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DetectorDemo, processingMessage, selectDroppedFile } from './_detector-demo';

function dispatchDrag(target: Element, type: string, files: File[], types = ['Files']) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'dataTransfer', {
    value: { files, types },
  });
  act(() => target.dispatchEvent(event));
}

describe('DetectorDemo drag-and-drop', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    act(() => root.render(<DetectorDemo />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

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
    const zone = container.querySelector('[data-drop-zone="true"]')!;

    dispatchDrag(zone, 'drop', [first, second]);

    expect(container.textContent).toContain('한 번에 파일 하나만 올려줘.');
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
  });

  it('파일 drag depth가 남아 있으면 active 안내를 유지한다', () => {
    const zone = container.querySelector('[data-drop-zone="true"]')!;

    dispatchDrag(zone, 'dragenter', []);
    dispatchDrag(zone, 'dragenter', []);
    dispatchDrag(zone, 'dragleave', []);
    expect(container.textContent).toContain('여기에 놓아줘');

    dispatchDrag(zone, 'dragleave', []);
    expect(container.textContent).toContain('사진·영상을 끌어 놓거나 파일 선택');
  });

  it('비파일 drag는 active 상태나 기존 파일 선택을 바꾸지 않는다', () => {
    const file = new File(['gecko'], 'selected.jpg', { type: 'image/jpeg' });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    act(() => input.dispatchEvent(new Event('change', { bubbles: true })));
    const zone = container.querySelector('[data-drop-zone="true"]')!;

    dispatchDrag(zone, 'dragenter', [], ['text/plain']);
    dispatchDrag(zone, 'drop', [], ['text/plain']);

    expect(container.textContent).toContain('선택됨: selected.jpg');
    expect(container.textContent).not.toContain('여기에 놓아줘');
    expect(container.querySelector('[aria-live="polite"]')).toBeNull();
  });

  it('단일 파일 drop과 기존 input 선택이 같은 검증·표시 경로를 쓴다', () => {
    const dropped = new File(['gecko'], 'dropped.jpg', { type: 'image/jpeg' });
    const zone = container.querySelector('[data-drop-zone="true"]')!;
    dispatchDrag(zone, 'drop', [dropped]);
    expect(container.textContent).toContain('선택됨: dropped.jpg');

    const selected = new File(['gecko'], 'clicked.jpg', { type: 'image/jpeg' });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { configurable: true, value: [selected] });
    act(() => input.dispatchEvent(new Event('change', { bubbles: true })));

    expect(container.textContent).toContain('선택됨: clicked.jpg');
  });
});

describe('DetectorDemo Preview 경계', () => {
  it('Preview에서 shadow 경계와 실제 worker 처리 문구를 표시한다', () => {
    const html = renderToStaticMarkup(<DetectorDemo previewEnabled />);

    expect(html).toContain('YOLO v2.1 보호 Preview');
    expect(html).toContain('production active 아님');
    expect(processingMessage(true)).toBe('v2.1 worker에 안전하게 전달하고 있어.');
  });

  it('기본 화면은 Preview 문구 없이 fake 계약을 유지한다', () => {
    const html = renderToStaticMarkup(<DetectorDemo previewEnabled={false} />);

    expect(html).not.toContain('YOLO v2.1 보호 Preview');
    expect(processingMessage(false)).toBe('연구용 감지 worker 계약을 확인하고 있어.');
  });
});
