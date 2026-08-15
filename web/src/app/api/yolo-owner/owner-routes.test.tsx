import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest, NextResponse } from 'next/server';

const { requireOwner, rpc, presignGet } = vi.hoisted(() => ({ requireOwner: vi.fn(), rpc: vi.fn(), presignGet: vi.fn() }));
vi.mock('@/lib/labelingAccess', () => ({ requireOwner }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc } }));
vi.mock('@/lib/r2', () => ({ presignGet, SIGNED_URL_TTL_SEC: 3600 }));

import { GET } from './reviews/route';
import { POST as DECIDE } from './reviews/[revisionId]/decision/route';
import { POST as ACTIVATE } from './models/[version]/activate/route';
import { POST as APPROVE_MODEL } from './models/[version]/approval/route';
import { POST as FREEZE_DATASET } from './datasets/[datasetId]/freeze/route';
import { OwnerYoloView } from '@/app/labeling/owner/yolo/_owner-yolo-view';

const REVISION = '11111111-1111-4111-8111-111111111111';
const DATASET = '22222222-2222-4222-8222-222222222222';
const overview = {
  reviews: [{
    revision_id: REVISION, task_id: '33333333-3333-4333-8333-333333333333', media_kind: 'image',
    media_url: 'https://example.test/image.jpg', frame_manifest: [{ frame_index: 0, timestamp_ms: 0 }],
    blind_boxes: [], blind_no_gecko: true, revision_boxes: [], revision_no_gecko: true,
    revision_reason: '게코 없음 확인', prediction: {
      request_id: 'req-1', media_kind: 'image', model_version: 'yolo-v1', provider_mode: 'worker',
      processed_at: '2026-08-10T08:00:00Z', warning: '연구용 결과이며 오류 가능', frames: [{ frame_index: 0, timestamp_ms: 0, detections: [] }],
      contribution_status: 'not_requested',
    }, internal_secret: 'drop',
  }],
  datasets: [{ id: DATASET, version: 'dataset-v2-draft' }],
  models: [{ version: 'yolo-v1', fixed_test_passed: true, future_holdout_passed: true, owner_approved: true, active: false }],
  active_model_version: null,
  internal_secret: 'drop',
};
const databaseOverview = {
  ...overview,
  reviews: overview.reviews.map(({ media_url: _mediaUrl, ...review }) => ({
    ...review,
    media_ref: 'private/owner-gecko.jpg',
  })),
};

function jsonRequest(url: string, body: unknown) {
  return new NextRequest(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
}

describe('YOLO owner routes', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    requireOwner.mockResolvedValue({ ok: true, userId: 'owner-1' });
    rpc.mockResolvedValue({ data: databaseOverview, error: null });
    presignGet.mockResolvedValue('https://signed.example/owner-gecko');
  });

  it('Owner만 allowlisted review/model overview를 읽는다', async () => {
    const response = await GET(new NextRequest('https://label.tera-ai.uk/api/yolo-owner/reviews'));
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_get_yolo_owner_overview', { p_owner_id: 'owner-1' });
    expect(presignGet).toHaveBeenCalledWith('private/owner-gecko.jpg', 3600);
    expect(JSON.stringify(await response.json())).not.toContain('internal_secret');

    requireOwner.mockResolvedValue({ ok: false, response: NextResponse.json({ detail: 'forbidden' }, { status: 403 }) });
    expect((await GET(new NextRequest('https://label.tera-ai.uk/api/yolo-owner/reviews'))).status).toBe(403);
  });

  it('승인은 Dataset version과 사유를 요구하고 같은 RPC에서 membership을 만든다', async () => {
    const url = `https://label.tera-ai.uk/api/yolo-owner/reviews/${REVISION}/decision`;
    expect((await DECIDE(jsonRequest(url, { decision: 'approve', reason: '사람 bbox 확인' }), { params: { revisionId: REVISION } })).status).toBe(400);
    const response = await DECIDE(jsonRequest(url, { decision: 'approve', reason: '사람 bbox 확인', dataset_version_id: DATASET }), { params: { revisionId: REVISION } });
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_owner_decide_yolo_bbox_revision', {
      p_owner_id: 'owner-1', p_revision_id: REVISION, p_decision: 'approve',
      p_reason: '사람 bbox 확인', p_dataset_version_id: DATASET,
    });
  });

  it('평가/승인 gate 실패는 409, rollback event는 명시 action으로 보낸다', async () => {
    const url = 'https://label.tera-ai.uk/api/yolo-owner/models/yolo-v1/activate';
    rpc.mockResolvedValueOnce({ data: null, error: { code: 'PT409', message: 'model_evaluations_required raw' } });
    expect((await ACTIVATE(jsonRequest(url, { action: 'activate', reason: '두 시험 통과 확인' }), { params: { version: 'yolo-v1' } })).status).toBe(409);
    rpc.mockResolvedValueOnce({ data: { active_model_version: 'yolo-v1', action: 'rollback' }, error: null });
    expect((await ACTIVATE(jsonRequest(url, { action: 'rollback', reason: '이전 버전 즉시 복귀' }), { params: { version: 'yolo-v1' } })).status).toBe(200);
    expect(rpc).toHaveBeenLastCalledWith('fn_activate_yolo_model', {
      p_owner_id: 'owner-1', p_model_version: 'yolo-v1', p_action: 'rollback', p_reason: '이전 버전 즉시 복귀',
    });
  });

  it('Owner model 승인도 별도 append-only RPC로 기록한다', async () => {
    const url = 'https://label.tera-ai.uk/api/yolo-owner/models/yolo-v1/approval';
    const response = await APPROVE_MODEL(
      jsonRequest(url, { decision: 'approve', reason: '고정 시험과 future holdout 확인' }),
      { params: { version: 'yolo-v1' } },
    );
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_owner_decide_yolo_model', {
      p_owner_id: 'owner-1', p_model_version: 'yolo-v1', p_decision: 'approve',
      p_reason: '고정 시험과 future holdout 확인',
    });
  });

  it('Dataset freeze를 별도 append-only RPC로 기록한다', async () => {
    const url = `https://label.tera-ai.uk/api/yolo-owner/datasets/${DATASET}/freeze`;
    const response = await FREEZE_DATASET(
      jsonRequest(url, { reason: 'Owner 승인 membership을 확인하고 Dataset 고정' }),
      { params: { datasetId: DATASET } },
    );
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledWith('fn_freeze_yolo_dataset', {
      p_owner_id: 'owner-1', p_dataset_version_id: DATASET,
      p_reason: 'Owner 승인 membership을 확인하고 Dataset 고정',
    });
  });
});

describe('OwnerYoloView', () => {
  it('Dataset 승인과 세 model gate를 수동 행동으로 표시한다', () => {
    const html = renderToStaticMarkup(<OwnerYoloView initial={overview} previewEnabled />);
    expect(html).toContain('Owner 승인 전 Dataset 미포함');
    expect(html).toContain('고정 시험 통과');
    expect(html).toContain('future holdout 통과');
    expect(html).toContain('Owner 모델 승인');
    expect(html).toContain('모델 승인 기록');
    expect(html).toContain('이전 버전으로 롤백');
    expect(html).toContain('bbox 검수 대상');
    expect(html).toContain('dataset-v2-draft');
    expect(html).toContain('Dataset freeze');
    expect(html).toContain('/labeling/owner/yolo/preview');
    expect(html).toContain('v2.5 bbox 제안 확인하기');
  });

  it('Preview config가 없으면 production Owner 화면에 v2.5 링크를 노출하지 않는다', () => {
    const html = renderToStaticMarkup(<OwnerYoloView initial={overview} />);
    expect(html).not.toContain('/labeling/owner/yolo/preview');
  });
});
