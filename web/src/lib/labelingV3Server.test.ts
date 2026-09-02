import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  mapGmeObservedMovingTimeRow,
  mapMotionDetailRow,
  mapMotionQueueRow,
  motionRpcErrorResponse,
  readGmeActiveDetectorIdentity,
  selectLatestSucceededPrediction,
  type GmeObservedMovingTimeRow,
  type MotionDetailRow,
  type MotionQueueRow,
  type VlmJobRow,
} from './labelingV3Server';

// server 매퍼 계약(구현계획 Task 2). raw provenance 미노출 + prediction 선택 결정론.

afterEach(() => {
  vi.unstubAllEnvs();
});

const GME_IDENTITY = 'a'.repeat(64);
const GME_RUN = '44444444-4444-4444-8444-444444444444';

function gmeRaw(
  overrides: Partial<GmeObservedMovingTimeRow> = {},
): GmeObservedMovingTimeRow {
  return {
    run_id: GME_RUN,
    detector_identity: GME_IDENTITY,
    measurement_status: 'measured',
    moving_time_sec: 0,
    visible_sec: 12.5,
    unknown_sec: 1,
    camera_motion_sec: 0,
    ...overrides,
  };
}

describe('mapGmeObservedMovingTimeRow', () => {
  it('관측된 정지 상태의 숫자 0을 보존하고 공개 7필드만 반환한다', () => {
    const raw = {
      ...gmeRaw(),
      state_intervals: [{ state: 'moving' }],
      permanent_artifact_key: 'secret-key',
    } as GmeObservedMovingTimeRow;
    expect(mapGmeObservedMovingTimeRow(raw)).toEqual({
      run_id: GME_RUN,
      detector_identity: GME_IDENTITY,
      measurement_status: 'measured',
      moving_time_sec: 0,
      visible_sec: 12.5,
      unknown_sec: 1,
      camera_motion_sec: 0,
    });
    expect(JSON.stringify(mapGmeObservedMovingTimeRow(raw))).not.toContain(
      'secret-key',
    );
  });

  it('Postgres numeric 문자열을 안전한 number로 정규화한다', () => {
    expect(
      mapGmeObservedMovingTimeRow(
        gmeRaw({
          moving_time_sec: '1.25',
          visible_sec: '9.5',
          unknown_sec: '0',
          camera_motion_sec: '2.75',
        }),
      ),
    ).toMatchObject({
      moving_time_sec: 1.25,
      visible_sec: 9.5,
      unknown_sec: 0,
      camera_motion_sec: 2.75,
    });
  });

  it('미관측은 run provenance와 visible=0을 보존하되 숫자는 null이다', () => {
    expect(
      mapGmeObservedMovingTimeRow(
        gmeRaw({
          measurement_status: 'not_observed',
          moving_time_sec: null,
          visible_sec: 0,
        }),
      ),
    ).toMatchObject({
      run_id: GME_RUN,
      measurement_status: 'not_observed',
      moving_time_sec: null,
      visible_sec: 0,
    });
  });

  it('pending과 run 없는 failed는 숫자·근거 초가 모두 null이다', () => {
    for (const measurement_status of ['pending', 'failed'] as const) {
      expect(
        mapGmeObservedMovingTimeRow(
          gmeRaw({
            run_id: null,
            measurement_status,
            moving_time_sec: null,
            visible_sec: null,
            unknown_sec: null,
            camera_motion_sec: null,
          }),
        ),
      ).toMatchObject({ measurement_status, moving_time_sec: null });
    }
  });

  it('0초 오용·음수·비정상 identity·미지 상태를 거부한다', () => {
    const invalidRows: GmeObservedMovingTimeRow[] = [
      gmeRaw({ measurement_status: 'not_observed', moving_time_sec: 0, visible_sec: 0 }),
      gmeRaw({ moving_time_sec: -1 }),
      gmeRaw({ detector_identity: 'old-model' }),
      gmeRaw({ measurement_status: 'unknown' }),
      gmeRaw({ moving_time_sec: 13, visible_sec: 12.5 }),
    ];
    for (const row of invalidRows) {
      expect(() => mapGmeObservedMovingTimeRow(row)).toThrow(
        'invalid_gme_observed_moving_time',
      );
    }
  });
});

describe('readGmeActiveDetectorIdentity', () => {
  it('64자리 소문자 SHA identity만 반환한다', () => {
    vi.stubEnv('GME_ACTIVE_DETECTOR_IDENTITY', GME_IDENTITY);
    expect(readGmeActiveDetectorIdentity()).toBe(GME_IDENTITY);
  });

  it('누락·대문자·공백 포함 설정은 원문 없이 거부한다', () => {
    for (const raw of ['', 'A'.repeat(64), `${GME_IDENTITY} `]) {
      vi.stubEnv('GME_ACTIVE_DETECTOR_IDENTITY', raw);
      expect(() => readGmeActiveDetectorIdentity()).toThrow(
        'invalid_gme_active_detector_identity_configuration',
      );
    }
  });
});

function queueRaw(overrides: Partial<MotionQueueRow> = {}): MotionQueueRow {
  return {
    clip_id: '11111111-1111-4111-8111-111111111111',
    camera_id: '22222222-2222-4222-8222-222222222222',
    camera_name: '2번 카메라',
    started_at: '2026-07-21T16:30:00.123456+09:00',
    duration_sec: 30,
    media_ready: true,
    state: 'unreviewed',
    session_stage: null,
    state_updated_at: null,
    // 방어: RPC 는 이런 raw 를 반환하지 않지만, 매퍼가 통과시키지 않아야 한다.
    r2_key: 'terra-clips/clips/secret.mp4',
    evidence_snapshot: { rank_features: { motion_summary: 1 } },
    owner_id: '33333333-3333-4333-8333-333333333333',
    ...overrides,
  } as MotionQueueRow;
}

describe('mapMotionQueueRow', () => {
  it('공개 8필드만 반환하고 raw provenance 를 제거한다', () => {
    const raw = queueRaw();
    expect(mapMotionQueueRow(raw)).toEqual({
      id: raw.clip_id,
      camera_id: raw.camera_id,
      camera_name: raw.camera_name,
      started_at: raw.started_at,
      duration_sec: raw.duration_sec,
      media_ready: true,
      state: 'unreviewed',
      session_stage: null,
    });
  });

  it('r2_key/evidence/owner_id 가 직렬화 결과에 없다', () => {
    const json = JSON.stringify(mapMotionQueueRow(queueRaw()));
    expect(json).not.toContain('r2_key');
    expect(json).not.toContain('evidence');
    expect(json).not.toContain('owner_id');
    expect(json).not.toContain('rank_features');
  });

  it('started_at 마이크로초를 문자열 그대로 보존한다', () => {
    expect(mapMotionQueueRow(queueRaw()).started_at).toBe(
      '2026-07-21T16:30:00.123456+09:00',
    );
  });

  it('owner_decision 상태와 session_stage 를 매핑한다', () => {
    const item = mapMotionQueueRow(
      queueRaw({ state: 'label', session_stage: 'gt_locked' }),
    );
    expect(item.state).toBe('label');
    expect(item.session_stage).toBe('gt_locked');
  });

  it('미지 상태값은 던진다', () => {
    expect(() => mapMotionQueueRow(queueRaw({ state: 'quarantine' }))).toThrow(
      'invalid_motion_state',
    );
  });
});

function detailRaw(session: MotionDetailRow['session'] = null): MotionDetailRow {
  return {
    clip_id: '11111111-1111-4111-8111-111111111111',
    camera_id: '22222222-2222-4222-8222-222222222222',
    camera_name: '2번 카메라',
    started_at: '2026-07-21T16:30:00.123456+09:00',
    duration_sec: 30,
    media_ready: true,
    state: 'label',
    state_updated_at: '2026-07-21T16:31:00.222222+09:00',
    session,
  };
}

describe('mapMotionDetailRow', () => {
  it('세션 없으면 prediction 속성 자체가 없다(GT 잠금 전 blind)', () => {
    const detail = mapMotionDetailRow(detailRaw(null));
    expect(detail.session).toBeNull();
    expect(detail.state_updated_at).toBe('2026-07-21T16:31:00.222222+09:00');
    expect(detail).not.toHaveProperty('prediction');
    expect(JSON.stringify(detail)).not.toContain('rank_features');
    expect(JSON.stringify(detail)).not.toContain('motion_summary');
  });

  it('gt_locked 세션이면 prediction 을 노출한다', () => {
    const detail = mapMotionDetailRow(
      detailRaw({
        stage: 'gt_locked',
        initial_gt: { primary_action: 'moving' },
        current_gt: { primary_action: 'moving' },
        prediction_snapshot: { action: 'drinking', confidence: 0.9 },
        vlm_verdict: null,
        vlm_error_tags: null,
        vlm_review_note: null,
        completion_reason: null,
        gt_locked_at: '2026-07-21T16:31:00Z',
        completed_at: null,
      }),
    );
    expect(detail.session?.stage).toBe('gt_locked');
    expect(detail.prediction).toEqual({ action: 'drinking', confidence: 0.9 });
    expect(detail.session?.vlm_error_tags).toEqual([]);
  });

  it('completed 세션이면 verdict/prediction 을 노출한다', () => {
    const detail = mapMotionDetailRow(
      detailRaw({
        stage: 'completed',
        initial_gt: { primary_action: 'moving' },
        current_gt: { primary_action: 'moving' },
        prediction_snapshot: { action: 'moving' },
        vlm_verdict: 'correct',
        vlm_error_tags: ['none'],
        vlm_review_note: null,
        completion_reason: 'vlm_reviewed',
        gt_locked_at: '2026-07-21T16:31:00Z',
        completed_at: '2026-07-21T16:32:00Z',
      }),
    );
    expect(detail.session?.stage).toBe('completed');
    expect(detail.session?.vlm_verdict).toBe('correct');
    expect(detail.prediction).toEqual({ action: 'moving' });
  });
});

describe('selectLatestSucceededPrediction', () => {
  const succeeded = (id: string, completed_at: string, result: unknown): VlmJobRow => ({
    id,
    status: 'succeeded',
    result,
    completed_at,
  });

  it('성공 job 이 없으면 null', () => {
    expect(
      selectLatestSucceededPrediction([
        { id: 'a', status: 'failed_terminal', result: { x: 1 }, completed_at: '2026-07-21T00:00:00Z' },
        { id: 'b', status: 'failed_retryable', result: { x: 2 }, completed_at: '2026-07-21T01:00:00Z' },
        { id: 'c', status: 'queued', result: null, completed_at: null },
      ]),
    ).toBeNull();
  });

  it('object result 성공 job 만, completed_at DESC → id DESC 로 최신 선택', () => {
    const rows: VlmJobRow[] = [
      succeeded('a', '2026-07-21T00:00:00Z', { pick: 'old' }),
      succeeded('c', '2026-07-21T02:00:00Z', { pick: 'newest-tie-low-id' }),
      succeeded('z', '2026-07-21T02:00:00Z', { pick: 'newest-tie-high-id' }),
    ];
    // 동일 completed_at → id DESC 이므로 'z' 가 이긴다.
    expect(selectLatestSucceededPrediction(rows)).toEqual({ pick: 'newest-tie-high-id' });
  });

  it('배열/스칼라 result 는 무시한다', () => {
    expect(
      selectLatestSucceededPrediction([
        succeeded('a', '2026-07-21T03:00:00Z', [1, 2, 3]),
        succeeded('b', '2026-07-21T02:00:00Z', 'moving'),
      ]),
    ).toBeNull();
  });

  it('원본 row 를 앨리어싱하지 않는 deep clone 을 반환한다', () => {
    const result = { nested: { action: 'moving' } };
    const rows: VlmJobRow[] = [succeeded('a', '2026-07-21T00:00:00Z', result)];
    const snapshot = selectLatestSucceededPrediction(rows) as {
      nested: { action: string };
    };
    snapshot.nested.action = 'mutated';
    expect(result.nested.action).toBe('moving');
  });
});

describe('motionRpcErrorResponse', () => {
  it('알려진 안정 SQLSTATE 를 공개 상태코드로 매핑한다', async () => {
    const cases: Array<[string, number, string]> = [
      ['22023', 400, 'invalid_request'],
      ['P0002', 404, 'not_found'],
      ['PT409', 409, 'stale_state'],
      ['PT410', 409, 'labeling_started'],
      ['PT422', 409, 'media_unavailable'],
      ['PT423', 409, 'gt_locked'],
    ];
    for (const [code, status, expected] of cases) {
      const res = motionRpcErrorResponse({ code });
      expect(res).not.toBeNull();
      expect(res!.status).toBe(status);
      const body = await res!.json();
      expect(body.code).toBe(expected);
    }
  });

  it('PT424(hold/skip 결정 충돌) 을 안정 409 decision_blocks_labeling 으로 매핑한다', async () => {
    const res = motionRpcErrorResponse({ code: 'PT424', message: 'raw secret' });
    expect(res?.status).toBe(409);
    expect(await res?.json()).toEqual({
      detail: '보류 또는 제외된 영상이야. 먼저 라벨 대상으로 보내줘.',
      code: 'decision_blocks_labeling',
    });
  });

  it('labeler_forbidden(PT403) 은 존재를 숨기는 404 로 매핑한다', async () => {
    const res = motionRpcErrorResponse({ code: 'PT403' });
    expect(res!.status).toBe(404);
    const body = await res!.json();
    expect(body.code).toBe('not_found');
  });

  it('미지 코드는 null(호출부가 502 로 처리)', () => {
    expect(motionRpcErrorResponse({ code: 'XX999' })).toBeNull();
    expect(motionRpcErrorResponse({})).toBeNull();
    expect(motionRpcErrorResponse(null)).toBeNull();
  });

  it('공개 응답에 Postgres 원문 메시지를 담지 않는다', async () => {
    const res = motionRpcErrorResponse({
      code: 'PT409',
      message: 'stale_state at public.fn_decide_motion_clip_labeling line 42',
    });
    const body = await res!.json();
    expect(JSON.stringify(body)).not.toContain('fn_decide_motion_clip_labeling');
    expect(JSON.stringify(body)).not.toContain('line 42');
  });
});
