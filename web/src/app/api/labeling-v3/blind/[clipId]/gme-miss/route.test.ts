import { describe, expect, it } from 'vitest';

import { POST } from './route';

describe('POST blind legacy GME miss', () => {
  it('구 원장으로 새 기록을 나누지 않고 통합 endpoint를 안내한다', async () => {
    const response = await POST();

    expect(response.status).toBe(410);
    await expect(response.json()).resolves.toMatchObject({
      code: 'gme_feedback_endpoint_moved',
    });
  });
});
