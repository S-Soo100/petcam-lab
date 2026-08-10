import { describe, expect, it } from 'vitest';

import { POST } from './route';

const jpeg = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 1]);

describe('POST /api/yolo-demo/infer', () => {
  it('실제 multipart 요청을 versioned detection DTO로 바꾼다', async () => {
    const data = new FormData();
    data.set('media', new File([jpeg], 'gecko.jpg', { type: 'image/jpeg' }));
    data.set('training_consent', 'true');
    const response = await POST(
      new Request('http://localhost/api/yolo-demo/infer', {
        method: 'POST',
        headers: { 'x-forwarded-for': '198.51.100.24' },
        body: data,
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    await expect(response.json()).resolves.toMatchObject({
      media_kind: 'image',
      model_version: 'fake-yolo-v0',
      provider_mode: 'fake',
      contribution_status: 'candidate_only',
    });
  });
});
