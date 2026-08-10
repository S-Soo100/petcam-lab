import type { HumanBox } from './yoloContribution';
import type { NormalizedBox } from './yoloDetection';

export interface Point {
  x: number;
  y: number;
}

export type ResizeHandle = 'nw' | 'ne' | 'sw' | 'se';

const MIN_SIZE = 0.005;

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

function stable(value: number): number {
  return Math.round(value * 1_000_000) / 1_000_000;
}

export function createBox(start: Point, end: Point): NormalizedBox | null {
  const startX = clamp(start.x);
  const startY = clamp(start.y);
  const endX = clamp(end.x);
  const endY = clamp(end.y);
  const x = Math.min(startX, endX);
  const y = Math.min(startY, endY);
  const width = Math.abs(endX - startX);
  const height = Math.abs(endY - startY);
  return width >= MIN_SIZE && height >= MIN_SIZE
    ? { x: stable(x), y: stable(y), width: stable(width), height: stable(height) }
    : null;
}

export function moveBox(box: NormalizedBox, dx: number, dy: number): NormalizedBox {
  return {
    ...box,
    x: clamp(box.x + dx, 0, 1 - box.width),
    y: clamp(box.y + dy, 0, 1 - box.height),
  };
}

export function resizeBox(
  box: NormalizedBox,
  handle: ResizeHandle,
  dx: number,
  dy: number,
): NormalizedBox {
  const right = box.x + box.width;
  const bottom = box.y + box.height;
  const nextLeft = handle.includes('w') ? clamp(box.x + dx, 0, right - MIN_SIZE) : box.x;
  const nextTop = handle.includes('n') ? clamp(box.y + dy, 0, bottom - MIN_SIZE) : box.y;
  const nextRight = handle.includes('e') ? clamp(right + dx, nextLeft + MIN_SIZE, 1) : right;
  const nextBottom = handle.includes('s') ? clamp(bottom + dy, nextTop + MIN_SIZE, 1) : bottom;
  return {
    x: nextLeft,
    y: nextTop,
    width: nextRight - nextLeft,
    height: nextBottom - nextTop,
  };
}

export function boxesForFrame(items: HumanBox[], frameIndex: number): HumanBox[] {
  return items.filter((item) => item.frame_index === frameIndex);
}
