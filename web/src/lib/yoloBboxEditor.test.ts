import { describe, expect, it } from 'vitest';

import { boxesForFrame, createBox, moveBox, resizeBox } from './yoloBboxEditor';

describe('normalized bbox editor math', () => {
  it('drag 좌표를 0..1 박스로 clamp하고 너무 작은 박스는 버린다', () => {
    expect(createBox({ x: 0.8, y: 0.8 }, { x: 1.2, y: 1.1 })).toEqual({
      x: 0.8, y: 0.8, width: 0.2, height: 0.2,
    });
    expect(createBox({ x: 0.2, y: 0.2 }, { x: 0.201, y: 0.201 })).toBeNull();
  });

  it('이동과 resize가 canvas 밖으로 나가지 않는다', () => {
    const box = { x: 0.2, y: 0.2, width: 0.3, height: 0.4 };
    expect(moveBox(box, -1, 0)).toEqual({ ...box, x: 0 });
    expect(resizeBox(box, 'se', 1, 1)).toEqual({ x: 0.2, y: 0.2, width: 0.8, height: 0.8 });
  });

  it('현재 frame 박스만 선택한다', () => {
    const items = [
      { frame_index: 1, bbox: { x: 0, y: 0, width: 0.1, height: 0.1 } },
      { frame_index: 12, bbox: { x: 0.2, y: 0.2, width: 0.3, height: 0.3 } },
    ];
    expect(boxesForFrame(items, 12)).toEqual([items[1]]);
  });
});
