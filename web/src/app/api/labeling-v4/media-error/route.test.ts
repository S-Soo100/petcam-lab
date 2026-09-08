import { NextRequest, NextResponse } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { requireLabelingAccess } = vi.hoisted(() => ({ requireLabelingAccess: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireLabelingAccess }));

import { POST } from './route';

const CLIP = '00000000-0000-4000-8000-000000000001';
const post = (body: unknown) => POST(new NextRequest('https://label.tera-ai.uk/api/labeling-v4/media-error', { method: 'POST', body: JSON.stringify(body) }));

beforeEach(() => {
  vi.clearAllMocks();
  requireLabelingAccess.mockResolvedValue({ ok: true, userId: 'labeler-1-uuid', isOwner: false });
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe('POST /api/labeling-v4/media-error', () => {
  it('유효한 보고는 [media-error] 한 줄을 남기고 ok', async () => {
    const res = await post({ clip_id: CLIP, attempt: 2, outcome: 'recovered' });
    expect(res.status).toBe(200);
    expect(console.warn).toHaveBeenCalledWith('[media-error]', expect.stringContaining('"outcome":"recovered"'));
  });
  it('잘못된 clip/outcome 은 400, 미승인은 가드 응답', async () => {
    expect((await post({ clip_id: 'nope', outcome: 'retrying' })).status).toBe(400);
    expect((await post({ clip_id: CLIP, outcome: 'boom' })).status).toBe(400);
    requireLabelingAccess.mockResolvedValue({ ok: false, response: NextResponse.json({}, { status: 403 }) });
    expect((await post({ clip_id: CLIP, outcome: 'retrying' })).status).toBe(403);
  });
});
