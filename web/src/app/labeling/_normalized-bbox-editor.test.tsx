import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createRef } from 'react';

import NormalizedBboxEditor, {
  beginBboxPointer,
  displayedVideoRect,
  finishBboxPointer,
  moveBboxPointer,
  normalizeDrag,
} from './_normalized-bbox-editor';

describe('normalizeDrag', () => {
  it('converts a pointer drag to a normalized box', () => {
    expect(
      normalizeDrag(
        { x: 20, y: 10 },
        { x: 80, y: 70 },
        { left: 0, top: 0, width: 100, height: 100 },
      ),
    ).toEqual({ x: 0.2, y: 0.1, width: 0.6, height: 0.6 });
  });

  it('supports any drag direction and clamps outside points', () => {
    expect(
      normalizeDrag(
        { x: 120, y: 90 },
        { x: -20, y: -10 },
        { left: 0, top: 0, width: 100, height: 100 },
      ),
    ).toEqual({ x: 0, y: 0, width: 1, height: 0.9 });
  });

  it('rejects boxes smaller than 0.005 in either dimension and zero-sized rects', () => {
    expect(
      normalizeDrag(
        { x: 10, y: 10 },
        { x: 10.4, y: 80 },
        { left: 0, top: 0, width: 100, height: 100 },
      ),
    ).toBeNull();
    expect(
      normalizeDrag(
        { x: 10, y: 10 },
        { x: 80, y: 10.4 },
        { left: 0, top: 0, width: 100, height: 100 },
      ),
    ).toBeNull();
    expect(
      normalizeDrag(
        { x: 0, y: 0 },
        { x: 1, y: 1 },
        { left: 0, top: 0, width: 0, height: 100 },
      ),
    ).toBeNull();
  });
});

describe('displayedVideoRect', () => {
  it('removes horizontal letterboxing using the intrinsic video ratio', () => {
    expect(displayedVideoRect({ left: 10, top: 20, width: 200, height: 200 }, 1600, 800)).toEqual({
      left: 10,
      top: 70,
      width: 200,
      height: 100,
    });
  });

  it('removes vertical letterboxing using the intrinsic video ratio', () => {
    expect(displayedVideoRect({ left: 10, top: 20, width: 200, height: 100 }, 100, 100)).toEqual({
      left: 60,
      top: 20,
      width: 100,
      height: 100,
    });
  });
});

describe('bbox pointer interaction', () => {
  it('captures pointer, previews drag, commits on up, and releases capture', () => {
    const captured = new Set<number>();
    const target = {
      setPointerCapture: (id: number) => { captured.add(id); },
      hasPointerCapture: (id: number) => captured.has(id),
      releasePointerCapture: (id: number) => { captured.delete(id); },
    };
    const start = { current: null as { x: number; y: number } | null };
    const changes: unknown[] = [];
    beginBboxPointer(start, target, 9, { x: 20, y: 10 });
    expect(captured.has(9)).toBe(true);
    expect(moveBboxPointer(start, { x: 80, y: 70 }, { left: 0, top: 0, width: 100, height: 100 })).toEqual({
      x: 0.2, y: 0.1, width: 0.6, height: 0.6,
    });
    expect(finishBboxPointer(start, target, 9, { x: 80, y: 70 }, { left: 0, top: 0, width: 100, height: 100 }, true, (box) => changes.push(box))).toBe(true);
    expect(changes).toEqual([{ x: 0.2, y: 0.1, width: 0.6, height: 0.6 }]);
    expect(start.current).toBeNull();
    expect(captured.has(9)).toBe(false);
  });

  it('releases pointer on cancel without committing onChange', () => {
    const captured = new Set<number>();
    const target = {
      setPointerCapture: (id: number) => { captured.add(id); },
      hasPointerCapture: (id: number) => captured.has(id),
      releasePointerCapture: (id: number) => { captured.delete(id); },
    };
    const start = { current: null as { x: number; y: number } | null };
    const changes: unknown[] = [];
    beginBboxPointer(start, target, 3, { x: 10, y: 10 });
    expect(finishBboxPointer(start, target, 3, { x: 90, y: 90 }, { left: 0, top: 0, width: 100, height: 100 }, false, (box) => changes.push(box))).toBe(false);
    expect(changes).toEqual([]);
    expect(captured.has(3)).toBe(false);
  });
});

describe('NormalizedBboxEditor markup', () => {
  it('offers labelled pointer/touch overlay plus keyboard-accessible redraw and clear controls', () => {
    const html = renderToStaticMarkup(
      <NormalizedBboxEditor
        videoRef={createRef<HTMLVideoElement>()}
        value={{ x: 0.1, y: 0.2, width: 0.3, height: 0.4 }}
        onChange={() => {}}
      >
        <div>video</div>
      </NormalizedBboxEditor>,
    );
    expect(html).toContain('aria-label="게코 위치 bbox 그리기 영역"');
    expect(html).toContain('touch-none');
    expect(html).toContain('bbox 다시 그리기');
    expect(html).toContain('bbox 지우기');
    expect(html).toContain('min-h-11');
    expect(html.match(/<rect/g)).toHaveLength(2);
    expect(html).toContain('stroke="#18181b"');
    expect(html).toContain('stroke-width="4"');
    expect(html).toContain('stroke="#facc15"');
    expect(html).toContain('stroke-width="2"');
    expect(html).toContain('vector-effect="non-scaling-stroke"');
    expect(html).toContain('fill="rgba(16,185,129,0.18)"');
  });

  it('keeps the video host mounted while bbox controls are disabled', () => {
    const html = renderToStaticMarkup(
      <NormalizedBboxEditor
        enabled={false}
        videoRef={createRef<HTMLVideoElement>()}
        value={null}
        onChange={() => {}}
      >
        <div data-video-host>video</div>
      </NormalizedBboxEditor>,
    );
    expect(html).toContain('data-video-host');
    expect(html).not.toContain('bbox 다시 그리기');
    expect(html).not.toContain('게코 위치 bbox 그리기 영역');
  });

  it('renders a read-only reference bbox in the same content-rect SVG as the editable box', () => {
    const html = renderToStaticMarkup(
      <NormalizedBboxEditor
        enabled={false}
        videoRef={createRef<HTMLVideoElement>()}
        value={null}
        referenceValue={{ x: 0.1, y: 0.2, width: 0.3, height: 0.4 }}
        onChange={() => {}}
      >
        <div data-video-host>video and external controls</div>
      </NormalizedBboxEditor>,
    );

    expect(html).toContain('data-overlay="reference-bbox"');
    expect(html).toContain('aria-label="검수자 effective bbox"');
    expect(html).toContain('x="0.1"');
    expect(html).toContain('y="0.2"');
    expect(html).toContain('width="0.3"');
    expect(html).toContain('height="0.4"');
  });
});
