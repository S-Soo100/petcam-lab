import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { requireOwner, from, presignGet } = vi.hoisted(() => ({ requireOwner: vi.fn(), from: vi.fn(), presignGet: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));
vi.mock('@/lib/r2', () => ({ presignGet }));

import { GET } from './route';

function chain(result: unknown) {
  const value: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'single']) value[method] = vi.fn(() => value);
  value.then = (resolve: (result: unknown) => unknown) => resolve(result);
  return value;
}

const ID = '380d97fd-0000-4000-8000-000000000001';

describe('GET RAP recording detail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
    presignGet.mockResolvedValueOnce('https://signed/video').mockResolvedValueOnce('https://signed/thumb');
  });

  it('presigns uploaded media but does not return raw object keys', async () => {
    from.mockReturnValue(chain({ data: {
      id: ID, mode: 'test', camera_key: 'cam01', test_run_id: 'test-x', night_date: null,
      scheduled_start_utc: '2026-08-26T11:00:00Z', actual_start_utc: '2026-08-26T11:00:00Z',
      partial: false, duration_sec: 60, codec: 'hevc', width: 2880, height: 1620, fps: 20,
      video_size_bytes: 10, capture_status: 'captured', upload_status: 'uploaded', last_error_code: null,
      uploaded_at: '2026-08-26T11:02:00Z', video_r2_key: 'c500g/x/video.mp4',
      thumbnail_r2_key: 'c500g/x/thumbnail.jpg', log_r2_key: 'c500g/x/log',
      manifest_r2_key: 'c500g/x/manifest.json', video_sha256: 'a'.repeat(64), relative_bundle_path: 'x',
    }, error: null }));
    const response = await GET(new NextRequest(`https://x/api/research/rap/recordings/${ID}`), { params: { id: ID } });
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body.video_url).toBe('https://signed/video');
    expect(body.thumbnail_url).toBe('https://signed/thumb');
    expect(JSON.stringify(body)).not.toContain('r2_key');
    expect(presignGet).toHaveBeenCalledTimes(2);
  });

  it('rejects malformed ids before database and signing', async () => {
    const response = await GET(new NextRequest('https://x/api/research/rap/recordings/bad'), { params: { id: 'bad' } });
    expect(response.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
    expect(presignGet).not.toHaveBeenCalled();
  });
});
