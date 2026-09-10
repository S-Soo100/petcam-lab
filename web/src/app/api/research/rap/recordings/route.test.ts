import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, from } = vi.hoisted(() => ({ requireOwner: vi.fn(), from: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import { GET } from './route';

function chain(result: unknown) {
  const value: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'order', 'limit']) value[method] = vi.fn(() => value);
  value.then = (resolve: (result: unknown) => unknown) => resolve(result);
  return value;
}

function request(query = '') {
  return new NextRequest(`https://label.tera-ai.uk/api/research/rap/recordings${query}`);
}

describe('GET RAP recordings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner' });
  });

  it('returns owner guard response before database access', async () => {
    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    const response = await GET(request());
    expect(response.status).toBe(403);
    expect(from).not.toHaveBeenCalled();
  });

  it('returns safe summaries and coverage without storage identifiers', async () => {
    from.mockReturnValue(chain({ data: [{
      id: '380d97fd-0000-4000-8000-000000000001', mode: 'production', camera_key: 'cam01',
      test_run_id: null, night_date: '2026-08-26', scheduled_start_utc: '2026-08-26T11:00:00Z',
      actual_start_utc: '2026-08-26T11:00:00Z', partial: false, duration_sec: 1800, codec: 'hevc',
      width: 2880, height: 1620, fps: 20, video_size_bytes: 10, capture_status: 'captured',
      upload_status: 'uploaded', last_error_code: null, uploaded_at: '2026-08-26T11:31:00Z',
      video_r2_key: 'c500g/private/video.mp4', video_sha256: 'a'.repeat(64), relative_bundle_path: 'private',
    }], error: null }));
    const response = await GET(request('?mode=production&night=2026-08-26'));
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body.coverage.expected).toBe(72);
    expect(JSON.stringify(body)).not.toContain('r2_key');
    expect(JSON.stringify(body)).not.toContain('sha256');
    expect(JSON.stringify(body)).not.toContain('relative_bundle_path');
  });

  it('rejects invalid filters before database access', async () => {
    const response = await GET(request('?camera=cam99'));
    expect(response.status).toBe(400);
    expect(from).not.toHaveBeenCalled();
  });
});
