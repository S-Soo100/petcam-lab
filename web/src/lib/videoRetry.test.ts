import { describe, expect, it } from 'vitest';

import { VIDEO_RETRY_MAX, nextRetryDelayMs } from './videoRetry';

describe('nextRetryDelayMs', () => {
  it('1·2·4초 뒤 세 번, 그 다음은 null', () => {
    expect([0, 1, 2, 3].map(nextRetryDelayMs)).toEqual([1000, 2000, 4000, null]);
    expect(VIDEO_RETRY_MAX).toBe(3);
  });
  it('음수·정수 아님은 null', () => {
    expect(nextRetryDelayMs(-1)).toBeNull();
    expect(nextRetryDelayMs(1.5)).toBeNull();
  });
});
