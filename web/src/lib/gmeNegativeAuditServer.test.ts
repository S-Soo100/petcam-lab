import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { rpc, from } = vi.hoisted(() => ({ rpc: vi.fn(), from: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { rpc, from } }));

import {
  loadAuditDetail,
  loadAuditMediaKey,
  mapAuditRpcError,
  readAuditJsonBody,
  requireAuditAssignment,
} from './gmeNegativeAuditServer';

const ITEM = '11111111-1111-4111-8111-111111111111';
const REVIEWER = '22222222-2222-4222-8222-222222222222';

function assignment(overrides: Record<string, unknown> = {}) {
  return {
    item_id: ITEM,
    ordinal: 3,
    captured_at: '2026-08-23T10:00:00Z',
    duration_sec: '60',
    media_ready: true,
    initial_verdict: 'gecko_absent',
    initial_representative_sec: null,
    initial_bbox: null,
    effective_verdict: 'gecko_absent',
    effective_representative_sec: null,
    effective_bbox: null,
    ...overrides,
  };
}

function builder(result: unknown, calls: Array<[string, unknown[]]> = []) {
  const value: Record<string, unknown> = {};
  for (const method of ['select', 'eq', 'order', 'limit']) {
    value[method] = (...args: unknown[]) => {
      calls.push([method, args]);
      return value;
    };
  }
  value.then = (resolve: (resolved: unknown) => unknown) => Promise.resolve(result).then(resolve);
  return value;
}

describe('GME negative audit server boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    rpc.mockResolvedValue({ data: [assignment()], error: null });
    from.mockImplementation(() => builder({ data: [], error: null }));
  });

  it('binds only the bearer-derived reviewer id to the assignment RPC', async () => {
    const result = await requireAuditAssignment(REVIEWER, ITEM);
    expect(result.ok).toBe(true);
    expect(rpc).toHaveBeenCalledWith('fn_get_gme_negative_audit_item', {
      p_item_id: ITEM,
      p_reviewer_id: REVIEWER,
    });
  });

  it('folds unknown and wrong-reviewer items into stable 404 without table queries', async () => {
    rpc.mockResolvedValue({ data: [], error: null });
    const result = await loadAuditMediaKey(REVIEWER, ITEM);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.response.status).toBe(404);
      expect(await result.response.json()).toEqual({
        detail: '대상을 찾을 수 없어.',
        code: 'not_assigned',
      });
    }
    expect(from).not.toHaveBeenCalled();
  });

  it.each([
    ['22023', 400, 'invalid_request'],
    ['PT403', 404, 'not_assigned'],
    ['PT404', 404, 'not_assigned'],
    ['PT410', 409, 'already_submitted'],
    ['PT409', 409, 'stale_revision'],
    ['PT427', 410, 'batch_closed'],
    ['08006', 502, 'unavailable'],
  ])('maps RPC %s to stable %i %s without raw DB text', async (code, status, publicCode) => {
    const response = mapAuditRpcError({ code, message: 'secret table and item raw error' });
    expect(response.status).toBe(status);
    const body = await response.json();
    expect(body.code).toBe(publicCode);
    expect(JSON.stringify(body)).not.toContain('secret');
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('returns only the caller own effective revision after assignment', async () => {
    const queryCalls: Record<string, Array<[string, unknown[]]>> = {};
    from.mockImplementation((table: string) => {
      queryCalls[table] = [];
      if (table === 'gme_negative_audit_corrections') {
        return builder({ data: [{ digest: 'own-effective-revision' }], error: null }, queryCalls[table]);
      }
      return builder({ data: [{ digest: 'other-reviewer-revision' }], error: null }, queryCalls[table]);
    });

    const result = await loadAuditDetail(REVIEWER, ITEM);
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.item.revision).toBe('own-effective-revision');
    expect(queryCalls.gme_negative_audit_corrections).toContainEqual([
      'eq',
      ['reviewer_id', REVIEWER],
    ]);
    expect(from).not.toHaveBeenCalledWith('gme_negative_audit_submissions');
  });

  it('reads the motion clip key only after assignment succeeds', async () => {
    const tables: string[] = [];
    from.mockImplementation((table: string) => {
      tables.push(table);
      if (table === 'gme_negative_audit_items') {
        return builder({ data: [{ clip_id: 'clip-private-id' }], error: null });
      }
      if (table === 'motion_clips') {
        return builder({ data: [{ r2_key: 'private/source.mp4' }], error: null });
      }
      return builder({ data: [], error: null });
    });

    const result = await loadAuditMediaKey(REVIEWER, ITEM);
    expect(result).toEqual({ ok: true, r2Key: 'private/source.mp4' });
    expect(rpc.mock.invocationCallOrder[0]).toBeLessThan(from.mock.invocationCallOrder[0]);
    expect(tables).toEqual(['gme_negative_audit_items', 'motion_clips']);
  });
});

describe('bounded JSON reader', () => {
  function request(body: string, declared?: string, contentType = 'application/json') {
    return new NextRequest('https://label.tera-ai.uk/api/labeling-v3/gme-audit/item/submit', {
      method: 'POST',
      body,
      headers: {
        'content-type': contentType,
        ...(declared ? { 'content-length': declared } : {}),
      },
    });
  }

  function chunkedRequest(
    chunks: Uint8Array[],
    headers: Record<string, string> = { 'content-type': 'application/json' },
  ) {
    let index = 0;
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (index >= chunks.length) {
          controller.close();
          return;
        }
        controller.enqueue(chunks[index]);
        index += 1;
      },
      cancel() {
        cancelled = true;
      },
    });
    const req = new NextRequest(
      'https://label.tera-ai.uk/api/labeling-v3/gme-audit/item/submit',
      {
        method: 'POST',
        body,
        headers,
        duplex: 'half',
      } as unknown as ConstructorParameters<typeof NextRequest>[1],
    );
    return { req, wasCancelled: () => cancelled };
  }

  it.each([null, 'text/plain', 'multipart/form-data', 'application/merge-patch+json'])(
    'requires exact application/json media type, got %s',
    async (contentType) => {
      const req = new NextRequest(
        'https://label.tera-ai.uk/api/labeling-v3/gme-audit/item/submit',
        {
          method: 'POST',
          body: '{}',
          headers: contentType ? { 'content-type': contentType } : undefined,
        },
      );
      const result = await readAuditJsonBody(req);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.response.status).toBe(400);
    },
  );

  it('accepts application/json case-insensitively with optional parameters', async () => {
    const result = await readAuditJsonBody(request('{}', undefined, 'Application/JSON; Charset=UTF-8'));
    expect(result).toEqual({ ok: true, value: {} });
  });

  it('returns stable 400 for malformed JSON', async () => {
    const result = await readAuditJsonBody(request('{'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(400);
  });

  it('returns stable 413 before parsing declared or actual bodies over 16 KiB', async () => {
    const declared = await readAuditJsonBody(request('{}', String(16 * 1024 + 1)));
    expect(declared.ok).toBe(false);
    if (!declared.ok) expect(declared.response.status).toBe(413);

    const actual = await readAuditJsonBody(request(`{"x":"${'x'.repeat(17 * 1024)}"}`));
    expect(actual.ok).toBe(false);
    if (!actual.ok) expect(actual.response.status).toBe(413);
  });

  it('reads a no-content-length body incrementally and cancels at 16 KiB + 1', async () => {
    const encoder = new TextEncoder();
    const streamed = chunkedRequest([
      encoder.encode(' '.repeat(8 * 1024)),
      encoder.encode(' '.repeat(8 * 1024)),
      encoder.encode('x'),
      encoder.encode('must-not-buffer'),
    ]);
    const result = await readAuditJsonBody(streamed.req);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(413);
    expect(streamed.wasCancelled()).toBe(true);
  });

  it('does not trust a forged small content-length and still cancels oversized input', async () => {
    const encoder = new TextEncoder();
    const streamed = chunkedRequest(
      [
        encoder.encode(' '.repeat(10 * 1024)),
        encoder.encode(' '.repeat(7 * 1024)),
        encoder.encode('must-not-buffer'),
      ],
      { 'content-type': 'application/json', 'content-length': '2' },
    );
    const result = await readAuditJsonBody(streamed.req);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(413);
    expect(streamed.wasCancelled()).toBe(true);
  });

  it('parses valid chunked UTF-8 JSON without content-length', async () => {
    const encoder = new TextEncoder();
    const streamed = chunkedRequest([
      encoder.encode('{"verdict":"'),
      encoder.encode('gecko_absent"}'),
    ]);
    expect(await readAuditJsonBody(streamed.req)).toEqual({
      ok: true,
      value: { verdict: 'gecko_absent' },
    });
    expect(streamed.wasCancelled()).toBe(false);
  });

  it('rejects an empty JSON body as stable 400', async () => {
    const result = await readAuditJsonBody(request(''));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.response.status).toBe(400);
  });
});
