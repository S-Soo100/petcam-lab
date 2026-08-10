import { describe, expect, it } from 'vitest';

import {
  mapBlindWorkspace,
  parseHumanAnnotation,
  type BlindWorkspace,
} from './yoloContribution';

const taskId = '11111111-1111-4111-8111-111111111111';

describe('mapBlindWorkspace', () => {
  it('prediction/model/confidence를 버리고 blind allowlist만 반환한다', () => {
    const workspace = mapBlindWorkspace({
      enabled: true,
      total: 2,
      completed: 0,
      prediction: { confidence: 0.99 },
      next_task: {
        task_id: taskId,
        media_kind: 'image',
        media_url: 'https://example.test/image.jpg',
        frame_manifest: [{ frame_index: 0, timestamp_ms: 0, secret: 'drop' }],
        stage: 'blind',
        model_version: 'hidden-v1',
        confidence: 0.99,
      },
    });

    expect(workspace).toEqual<BlindWorkspace>({
      enabled: true,
      total: 2,
      completed: 0,
      next_task: {
        task_id: taskId,
        media_kind: 'image',
        media_url: 'https://example.test/image.jpg',
        frame_manifest: [{ frame_index: 0, timestamp_ms: 0 }],
        stage: 'blind',
      },
    });
    expect(JSON.stringify(workspace)).not.toMatch(/prediction|model_version|confidence|secret/);
  });
});

describe('parseHumanAnnotation', () => {
  it('normalized 사람 박스를 allowlist로 만든다', () => {
    expect(
      parseHumanAnnotation({
        boxes: [
          {
            frame_index: 0,
            bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4, ignored: true },
            ignored: true,
          },
        ],
        no_gecko: false,
        ignored: true,
      }),
    ).toEqual({
      boxes: [{ frame_index: 0, bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }],
      no_gecko: false,
    });
  });

  it('빈 박스는 명시적 no_gecko와 함께일 때만 허용한다', () => {
    expect(parseHumanAnnotation({ boxes: [], no_gecko: true })).toEqual({ boxes: [], no_gecko: true });
    expect(parseHumanAnnotation({ boxes: [], no_gecko: false })).toBeNull();
    expect(parseHumanAnnotation({ boxes: [{ frame_index: 0, bbox: { x: 0.9, y: 0, width: 0.2, height: 0.2 } }], no_gecko: false })).toBeNull();
  });
});
