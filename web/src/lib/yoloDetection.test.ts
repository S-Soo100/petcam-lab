import { describe, expect, it } from 'vitest';

import {
  frameAtTime,
  validateDetectionResult,
  type DetectionFrame,
  type GeckoDetectionResult,
} from './yoloDetection';

const frame0: DetectionFrame = {
  frame_index: 0,
  timestamp_ms: 0,
  detections: [
    {
      label: 'gecko',
      confidence: 0.87,
      bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    },
  ],
};

const valid: GeckoDetectionResult = {
  request_id: 'req-1',
  media_kind: 'video',
  model_version: 'fake-yolo-v0',
  provider_mode: 'fake',
  processed_at: '2026-08-10T08:00:00.000Z',
  warning: '연구용 결과이며 오류 가능',
  frames: [frame0, { frame_index: 1, timestamp_ms: 1000, detections: [] }],
  contribution_status: 'not_requested',
};

describe('validateDetectionResult', () => {
  it('provider 응답을 allowlist DTO로 검증한다', () => {
    expect(validateDetectionResult({ ...valid, ignored_secret: 'x' })).toEqual(valid);
  });

  it('음수 timestamp와 0..1 밖 confidence를 거부한다', () => {
    expect(
      validateDetectionResult({
        ...valid,
        frames: [{ ...frame0, timestamp_ms: -1 }],
      }),
    ).toBeNull();
    expect(
      validateDetectionResult({
        ...valid,
        frames: [
          {
            ...frame0,
            detections: [{ ...frame0.detections[0], confidence: 2 }],
          },
        ],
      }),
    ).toBeNull();
  });

  it('bbox 범위와 frame 정렬이 깨진 응답을 거부한다', () => {
    expect(
      validateDetectionResult({
        ...valid,
        frames: [
          {
            ...frame0,
            detections: [
              {
                ...frame0.detections[0],
                bbox: { x: 0.9, y: 0.2, width: 0.3, height: 0.4 },
              },
            ],
          },
        ],
      }),
    ).toBeNull();
    expect(
      validateDetectionResult({
        ...valid,
        frames: [
          { frame_index: 1, timestamp_ms: 1000, detections: [] },
          frame0,
        ],
      }),
    ).toBeNull();
  });
});

describe('frameAtTime', () => {
  it('현재 시각 이전의 가장 가까운 frame만 선택한다', () => {
    const frame1000 = valid.frames[1];
    expect(frameAtTime(valid.frames, 1200, 500)).toEqual(frame1000);
    expect(frameAtTime(valid.frames, 800, 500)).toBeNull();
    expect(frameAtTime(valid.frames, -1, 500)).toBeNull();
  });
});
