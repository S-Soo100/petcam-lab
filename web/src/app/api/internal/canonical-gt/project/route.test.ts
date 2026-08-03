import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { rpc } = vi.hoisted(() => ({ rpc: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));

import { GET } from './route';

function req(secret = 'cron-secret') {
  return new NextRequest('https://label.tera-ai.uk/api/internal/canonical-gt/project', {
    headers: { Authorization: `Bearer ${secret}` },
  });
}

describe('GET /api/internal/canonical-gt/project', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.CRON_SECRET = 'cron-secret';
    process.env.DEV_USER_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    delete process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED;
  });

  it('인증 실패와 기본 disabled 상태를 404로 숨긴다', async () => {
    expect((await GET(req('wrong'))).status).toBe(404);
    expect((await GET(req())).status).toBe(404);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('enabled 상태에서도 한 번에 500개만 projection한다', async () => {
    process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED = 'true';
    rpc
      .mockResolvedValueOnce({
        data: { scanned: 2, inserted: 2, conflicts: 0, already_present: 0, dry_run: false },
        error: null,
      })
      .mockResolvedValueOnce({ data: null, error: null });
    const response = await GET(req());
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenNthCalledWith(1, 'fn_project_motion_clip_canonical_gt', {
      p_owner_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      p_apply: true,
      p_limit: 500,
      p_after_source_id: null,
      p_projection_run_id: expect.any(String),
    });
    expect(rpc).toHaveBeenNthCalledWith(
      2,
      'fn_record_motion_clip_gt_projection_run',
      expect.objectContaining({ p_status: 'succeeded', p_scanned: 2, p_inserted: 2 }),
    );
  });

  it('projection 오류를 안정 코드로 기록하고 원문을 숨긴다', async () => {
    process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED = 'true';
    rpc
      .mockResolvedValueOnce({ data: null, error: { message: 'private database detail' } })
      .mockResolvedValueOnce({ data: null, error: null });
    const response = await GET(req());
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain('private database detail');
    expect(rpc).toHaveBeenNthCalledWith(
      2,
      'fn_record_motion_clip_gt_projection_run',
      expect.objectContaining({ p_status: 'failed', p_error_code: 'projection_rpc_failed' }),
    );
  });
});
