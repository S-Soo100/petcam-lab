import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock('./supabaseBrowser', () => ({
  getSupabaseBrowser: () => ({ auth: { getSession } }),
}));

import {
  AuditValidationError,
  mapAuditDetailRow,
  mapAuditQueueRow,
  validateAuditCorrection,
  validateAuditSubmission,
} from './gmeNegativeAudit';
import {
  correctAudit,
  getAuditItem,
  getAuditMedia,
  getAuditQueue,
  submitAudit,
} from './gmeNegativeAuditApi';

const VALID_PRESENT = {
  verdict: 'gecko_present',
  representative_sec: 4.2,
  bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
} as const;

function privateRow(overrides: Record<string, unknown> = {}) {
  return {
    item_id: '11111111-1111-4111-8111-111111111111',
    ordinal: 7,
    captured_at: '2026-08-23T10:00:00Z',
    duration_sec: '60.25',
    media_ready: true,
    submitted: true,
    completed: 4,
    total: 12,
    initial_verdict: 'gecko_absent',
    initial_representative_sec: null,
    initial_bbox: null,
    effective_verdict: 'gecko_present',
    effective_representative_sec: '4.2',
    effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    revision: 'opaque-own-revision',
    stratum: 'positive_control',
    gme_run_id: 'secret-run',
    detector_identity: 'secret-detector',
    gme_score: 0.99,
    media_sha256: 'secret-media-hash',
    source_r2_key: 'secret/source.mp4',
    control: true,
    assigned_reviewer_id: 'other-reviewer',
    ...overrides,
  };
}

describe('GME negative audit pure validation', () => {
  it('requires timestamp and one finite normalized box only for gecko_present', () => {
    expect(validateAuditSubmission(VALID_PRESENT, 60)).toEqual(VALID_PRESENT);
    expect(() =>
      validateAuditSubmission(
        { verdict: 'gecko_present', representative_sec: 61, bbox: null },
        60,
      ),
    ).toThrow(AuditValidationError);
    expect(() =>
      validateAuditSubmission(
        { verdict: 'gecko_absent', representative_sec: 1, bbox: null },
        60,
      ),
    ).toThrow(AuditValidationError);
  });

  it.each([
    { verdict: 'unknown', representative_sec: null, bbox: null },
    { verdict: 'gecko_absent', representative_sec: null },
    { verdict: 'gecko_absent', representative_sec: null, bbox: null, reviewer_id: 'forged' },
    { verdict: 'gecko_present', representative_sec: Number.NaN, bbox: VALID_PRESENT.bbox },
    { verdict: 'gecko_present', representative_sec: Number.POSITIVE_INFINITY, bbox: VALID_PRESENT.bbox },
    { verdict: 'gecko_present', representative_sec: Number.MAX_VALUE, bbox: VALID_PRESENT.bbox },
    { verdict: 'gecko_present', representative_sec: 1, bbox: { ...VALID_PRESENT.bbox, extra: 1 } },
    { verdict: 'gecko_present', representative_sec: 1, bbox: { x: 0.9, y: 0.2, width: 0.2, height: 0.4 } },
    { verdict: 'gecko_present', representative_sec: 1, bbox: { x: 0.1, y: 0.2, width: 0, height: 0.4 } },
  ])('rejects invalid or non-exact submission %#', (payload) => {
    expect(() => validateAuditSubmission(payload, 60)).toThrow(AuditValidationError);
  });

  it.each(['gecko_absent', 'uncertain', 'media_error'] as const)(
    'accepts %s only with null timestamp and bbox',
    (verdict) => {
      expect(
        validateAuditSubmission(
          { verdict, representative_sec: null, bbox: null },
          60,
        ),
      ).toEqual({ verdict, representative_sec: null, bbox: null });
    },
  );

  it('uses the actual finite positive clip duration', () => {
    expect(() => validateAuditSubmission(VALID_PRESENT, Number.NaN)).toThrow(AuditValidationError);
    expect(() => validateAuditSubmission(VALID_PRESENT, 0)).toThrow(AuditValidationError);
    expect(() => validateAuditSubmission(VALID_PRESENT, Number.MAX_VALUE)).toThrow(AuditValidationError);
    expect(validateAuditSubmission({ ...VALID_PRESENT, representative_sec: 60 }, 60)).toEqual({
      ...VALID_PRESENT,
      representative_sec: 60,
    });
  });

  it('validates correction exact keys, trimmed reason, and opaque revision', () => {
    expect(
      validateAuditCorrection(
        { ...VALID_PRESENT, reason: '  bbox correction  ', revision: 'rev-1' },
        60,
      ),
    ).toEqual({ ...VALID_PRESENT, reason: 'bbox correction', revision: 'rev-1' });
    expect(() =>
      validateAuditCorrection({ ...VALID_PRESENT, reason: '', revision: 'rev-1' }, 60),
    ).toThrow(AuditValidationError);
    expect(() =>
      validateAuditCorrection(
        { ...VALID_PRESENT, reason: 'fix', revision: 'rev-1', expected_submission_digest: 'forged' },
        60,
      ),
    ).toThrow(AuditValidationError);
  });
});

describe('GME negative audit public mappers', () => {
  it.each([
    'stratum',
    'gme_run_id',
    'detector_identity',
    'gme_score',
    'media_sha256',
    'source_r2_key',
    'control',
    'assigned_reviewer_id',
  ])('never exposes %s', (key) => {
    expect(JSON.stringify(mapAuditQueueRow(privateRow()))).not.toContain(key);
    expect(JSON.stringify(mapAuditDetailRow(privateRow()))).not.toContain(key);
  });

  it('maps the queue to its exact public allowlist and finite DB duration', () => {
    expect(mapAuditQueueRow(privateRow())).toEqual({
      item_id: '11111111-1111-4111-8111-111111111111',
      ordinal: 7,
      captured_at: '2026-08-23T10:00:00Z',
      duration_sec: 60.25,
      media_ready: true,
      submitted: true,
    });
  });

  it('maps own initial/effective values and opaque revision only', () => {
    const detail = mapAuditDetailRow(privateRow());
    expect(detail).toEqual({
      item_id: '11111111-1111-4111-8111-111111111111',
      ordinal: 7,
      captured_at: '2026-08-23T10:00:00Z',
      duration_sec: 60.25,
      media_ready: true,
      initial_verdict: 'gecko_absent',
      initial_representative_sec: null,
      initial_bbox: null,
      effective_verdict: 'gecko_present',
      effective_representative_sec: 4.2,
      effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
      revision: 'opaque-own-revision',
    });
    const json = JSON.stringify(detail);
    expect(json).not.toContain('digest');
    expect(json).not.toContain('hash');
  });
});

describe('GME negative audit browser API', () => {
  const queuePayload = {
    items: [
      {
        item_id: '11111111-1111-4111-8111-111111111111',
        ordinal: 7,
        captured_at: '2026-08-23T10:00:00Z',
        duration_sec: 60.25,
        media_ready: true,
        submitted: true,
      },
    ],
    completed: 4,
    total: 12,
  };
  const detailPayload = {
    item_id: '11111111-1111-4111-8111-111111111111',
    ordinal: 7,
    captured_at: '2026-08-23T10:00:00Z',
    duration_sec: 60.25,
    media_ready: true,
    initial_verdict: 'gecko_absent',
    initial_representative_sec: null,
    initial_bbox: null,
    effective_verdict: 'gecko_present',
    effective_representative_sec: 4.2,
    effective_bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
    revision: 'opaque-own-revision',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    getSession.mockResolvedValue({ data: { session: { access_token: 'browser-token' } } });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((path: string) => {
        let payload: unknown = detailPayload;
        if (path.endsWith('/queue')) payload = queuePayload;
        else if (path.endsWith('/file/url')) {
          payload = { url: 'https://r2.example/signed', expires_in: 300 };
        } else if (path.endsWith('/submit')) payload = { status: 'submitted' };
        else if (path.endsWith('/correct')) payload = { status: 'corrected' };
        return Promise.resolve(
          new Response(JSON.stringify(payload), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
        );
      }),
    );
  });

  it('uses the fixed blind queue/detail/media endpoints with bearer auth', async () => {
    await getAuditQueue();
    await getAuditItem('item-1');
    await getAuditMedia('item-1');
    expect(vi.mocked(fetch).mock.calls.map((call) => call[0])).toEqual([
      '/api/labeling-v3/gme-audit/queue',
      '/api/labeling-v3/gme-audit/item-1',
      '/api/labeling-v3/gme-audit/item-1/file/url',
    ]);
    for (const [, init] of vi.mocked(fetch).mock.calls) {
      expect((init?.headers as Record<string, string>).Authorization).toBe(
        'Bearer browser-token',
      );
    }
  });

  it('sends exact public submission and correction bodies without internal digest fields', async () => {
    await submitAudit('item-1', VALID_PRESENT);
    await correctAudit('item-1', {
      ...VALID_PRESENT,
      reason: 'bbox correction',
      revision: 'opaque-revision',
    });
    const submitBody = JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body));
    const correctBody = JSON.parse(String(vi.mocked(fetch).mock.calls[1][1]?.body));
    expect(submitBody).toEqual(VALID_PRESENT);
    expect(correctBody).toEqual({
      ...VALID_PRESENT,
      reason: 'bbox correction',
      revision: 'opaque-revision',
    });
    expect(JSON.stringify(correctBody)).not.toContain('digest');
  });

  it.each([null, 'text/plain', 'application/problem+json'])(
    'rejects a successful response without exact JSON media type: %s',
    async (contentType) => {
      vi.mocked(fetch).mockResolvedValueOnce(
        new Response(JSON.stringify(queuePayload), {
          status: 200,
          headers: contentType ? { 'content-type': contentType } : undefined,
        }),
      );
      await expect(getAuditQueue()).rejects.toMatchObject({
        name: 'ApiError',
        status: 502,
        code: 'invalid_response',
      });
    },
  );

  it('accepts successful application/json case-insensitively with parameters', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(queuePayload), {
        status: 200,
        headers: { 'content-type': 'Application/JSON; Charset=UTF-8' },
      }),
    );
    await expect(getAuditQueue()).resolves.toEqual(queuePayload);
  });

  it('turns successful JSON parse failure into a stable ApiError without raw body text', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response('{"secret":', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    let caught: unknown;
    try {
      await getAuditQueue();
    } catch (error) {
      caught = error;
    }
    expect(caught).toMatchObject({
      name: 'ApiError',
      status: 502,
      code: 'invalid_response',
    });
    expect(String((caught as Error).message)).not.toContain('secret');
  });

  it.each([
    ['queue', () => getAuditQueue(), { ...queuePayload, control: true }],
    [
      'queue numeric',
      () => getAuditQueue(),
      { ...queuePayload, items: [{ ...queuePayload.items[0], duration_sec: '60.25' }] },
    ],
    ['detail', () => getAuditItem('item-1'), { ...detailPayload, gme_score: 0.9 }],
    [
      'detail numeric',
      () => getAuditItem('item-1'),
      { ...detailPayload, effective_representative_sec: '4.2' },
    ],
    ['media', () => getAuditMedia('item-1'), { url: 'https://r2.example/signed', expires_in: '300' }],
    ['submit', () => submitAudit('item-1', VALID_PRESENT), { status: 'submitted', stratum: 'hidden' }],
    [
      'correct',
      () =>
        correctAudit('item-1', {
          ...VALID_PRESENT,
          reason: 'fix',
          revision: 'opaque-revision',
        }),
      { status: 'corrected', submission_digest: 'hidden' },
    ],
  ] as const)('rejects invalid or non-exact %s success shapes', async (_name, invoke, payload) => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    await expect(invoke()).rejects.toMatchObject({
      status: 502,
      code: 'invalid_response',
    });
  });
});
