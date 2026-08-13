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

  it('drop 뒤 native input의 이전 파일명을 지운다', () => {
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'value', {
      configurable: true,
      value: 'C:\\fakepath\\previous-video.mp4',
      writable: true,
    });
    const dropped = new File(['gecko'], 'dropped.jpg', { type: 'image/jpeg' });

    dispatchDrag(container.querySelector('[data-drop-zone="true"]')!, 'drop', [dropped]);

    expect(input.value).toBe('');
    expect(container.textContent).toContain('선택됨: dropped.jpg');
  });

  it('후보 detection이 0개면 게코 부재 판정이 아니라고 안내한다', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      request_id: '00000000-0000-4000-8000-000000000001',
      media_kind: 'image',
      model_version: 'yolo26n-owner-dataset-v2.3-warm-start+dbed3a2d8018',
      provider_mode: 'worker',
      processed_at: '2026-08-13T03:00:00.000Z',
      warning: '라벨링 보조 후보야. 박스가 없어도 게코 없음 판정이 아니야.',
      threshold: 0.25,
      development_only: true,
      usage_scope: 'labeling_bbox_assist_only',
      frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
      contribution_status: 'not_requested',
    })));
    const file = new File(['gecko'], 'candidate.jpg', { type: 'image/jpeg' });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    act(() => input.dispatchEvent(new Event('change', { bubbles: true })));

    await act(async () => {
      container.querySelector('form')!.dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true }),
      );
    });

    expect(container.textContent).toContain(
      '후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.',
    );
  });
});

describe('DetectorDemo assist 경계', () => {
  it('활성화된 assist에서 shadow 경계와 실제 worker 처리 문구를 표시한다', () => {
    const html = renderToStaticMarkup(<DetectorDemo assistEnabled />);

    expect(html).toContain('Development-only 라벨링 보조');
    expect(html).toContain('production 자동판정 모델이 아니야');
    expect(html).toContain('박스가 없어도 게코가 없다는 뜻은 아니야');
    expect(html).not.toContain('v2.3');
    expect(processingMessage(true)).toBe('라벨링 보조 worker에 안전하게 전달하고 있어.');
  });

  it('기본 화면은 assist 문구 없이 fake 계약을 유지한다', () => {
    const html = renderToStaticMarkup(<DetectorDemo assistEnabled={false} />);

    expect(html).not.toContain('Development-only 라벨링 보조');
    expect(processingMessage(false)).toBe('연구용 감지 worker 계약을 확인하고 있어.');
  });
});
