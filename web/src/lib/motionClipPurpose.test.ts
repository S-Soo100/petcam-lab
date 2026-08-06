import { describe, expect, it } from 'vitest';

import { isProductionLabelingMedia } from './motionClipPurpose';

describe('isProductionLabelingMedia', () => {
  it('production 목적의 canonical 운영 경로만 허용한다', () => {
    expect(
      isProductionLabelingMedia('production', 'terra-clips/clips/camera/day/clip.mp4'),
    ).toBe(true);
  });

  it.each([
    ['test', 'test/camera/day/clip.mp4'],
    ['production', 'research-quarantine/camera/day/clip.mp4'],
    ['production', 'research-excluded/camera/day/clip.mp4'],
    ['production', 'deleted/camera/day/clip.mp4'],
    [null, 'terra-clips/clips/camera/day/clip.mp4'],
    ['production', null],
    ['production', 'terra-clips/clips-malformed/clip.mp4'],
  ])('목적 또는 경로가 운영 계약과 다르면 거부한다: %s %s', (purpose, r2Key) => {
    expect(isProductionLabelingMedia(purpose, r2Key)).toBe(false);
  });
});
