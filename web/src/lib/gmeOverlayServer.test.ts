import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { from } = vi.hoisted(() => ({ from: vi.fn() }));
vi.mock('@/lib/supabase', () => ({ supabaseAdmin: { from } }));

import {
  fetchAndParseGmeOverlay,
  loadCurrentGmeOverlayStatus,
  MAX_GME_ARTIFACT_COMPRESSED_BYTES,
  parseGmeOverlayGzip,
} from './gmeOverlayServer';

const V26_IDENTITY = '89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7';
const CLIP_ID = '11111111-1111-4111-8111-111111111111';

function query(data: unknown[]) {
  const value: Record<string, ReturnType<typeof vi.fn>> = {};
  for (const method of ['select', 'eq', 'not', 'order']) {
    value[method] = vi.fn(() => value);
  }
  value.limit = vi.fn().mockResolvedValue({ data, error: null });
  return value;
}

describe('loadCurrentGmeOverlayStatus', () => {
  const originalIdentity = process.env.GME_ACTIVE_DETECTOR_IDENTITY;

  beforeEach(() => {
    vi.clearAllMocks();
    process.env.GME_ACTIVE_DETECTOR_IDENTITY = V26_IDENTITY;
  });

  afterEach(() => {
    if (originalIdentity === undefined) delete process.env.GME_ACTIVE_DETECTOR_IDENTITY;
    else process.env.GME_ACTIVE_DETECTOR_IDENTITY = originalIdentity;
  });

  it('active v2.6 identity만 조회하고 과거 v2.5 결과로 fallback하지 않는다', async () => {
    const jobQuery = query([{ id: 'job-1', status: 'processing', result_run_id: null }]);
    from.mockReturnValueOnce(jobQuery);

    await expect(loadCurrentGmeOverlayStatus(CLIP_ID)).resolves.toEqual({ state: 'pending' });
    expect(jobQuery.eq).toHaveBeenCalledWith('clip_id', CLIP_ID);
    expect(jobQuery.eq).toHaveBeenCalledWith('detector_identity', V26_IDENTITY);
    expect(from).toHaveBeenCalledTimes(1);
  });

  it('active identity job이 아직 없으면 안전하게 pending으로 반환한다', async () => {
    from.mockReturnValueOnce(query([]));
    await expect(loadCurrentGmeOverlayStatus(CLIP_ID)).resolves.toEqual({ state: 'pending' });
  });

  it('succeeded job도 같은 clip·job·identity의 ok run일 때만 ready로 반환한다', async () => {
    const jobQuery = query([{ id: 'job-1', status: 'succeeded', result_run_id: 'run-1' }]);
    const runQuery = query([{
      id: 'run-1',
      permanent_artifact_key: 'terra-derived/gme/v1/permanent/result.json.gz',
      permanent_artifact_sha256: 'b'.repeat(64),
      permanent_artifact_bytes: 100,
    }]);
    from.mockReturnValueOnce(jobQuery).mockReturnValueOnce(runQuery);

    await expect(loadCurrentGmeOverlayStatus(CLIP_ID)).resolves.toMatchObject({
      state: 'ready',
      source: { runId: 'run-1', overlayRevision: 'b'.repeat(64) },
    });
    expect(runQuery.eq).toHaveBeenCalledWith('job_id', 'job-1');
    expect(runQuery.eq).toHaveBeenCalledWith('clip_id', CLIP_ID);
    expect(runQuery.eq).toHaveBeenCalledWith('detector_identity', V26_IDENTITY);
    expect(runQuery.eq).toHaveBeenCalledWith('status', 'ok');
  });

  it('invalid active identity 설정은 DB 조회 전에 거부한다', async () => {
    process.env.GME_ACTIVE_DETECTOR_IDENTITY = 'v2.6';
    await expect(loadCurrentGmeOverlayStatus(CLIP_ID)).rejects.toThrow(/identity/i);
    expect(from).not.toHaveBeenCalled();
  });
});

function validGzip(): Buffer {
  return gzipSync(Buffer.from(JSON.stringify({
    schema_version: 'gme-artifact-v1',
    artifact_identity: { engine_schema_version: 'gme-v1' },
    duration_sec: 5,
    intervals: [],
    tracking_quality: {},
    track_points: [{
      track_id: 'secret-track-id',
      timestamp_sec: 1,
      bbox_norm: [0.1, 0.2, 0.3, 0.4],
      confidence: 0.9,
      provenance: 'observed',
    }],
  })));
}

describe('parseGmeOverlayGzip', () => {
  it('compressed SHA와 byte count를 검증한 뒤 익명 overlay만 반환한다', () => {
    const gzip = validGzip();
    const sha = createHash('sha256').update(gzip).digest('hex');

    const parsed = parseGmeOverlayGzip(gzip, sha, gzip.byteLength);
    expect(parsed.points[0].track_index).toBe(0);
    expect(JSON.stringify(parsed)).not.toContain('secret-track-id');
  });

  it('SHA 또는 DB byte count가 다르면 거부한다', () => {
    const gzip = validGzip();
    expect(() => parseGmeOverlayGzip(gzip, 'a'.repeat(64), gzip.byteLength)).toThrow(/sha/i);
    const sha = createHash('sha256').update(gzip).digest('hex');
    expect(() => parseGmeOverlayGzip(gzip, sha, gzip.byteLength + 1)).toThrow(/byte/i);
  });
});

describe('fetchAndParseGmeOverlay', () => {
  it('presigned response를 bounded read한다', async () => {
    const gzip = validGzip();
    const sha = createHash('sha256').update(gzip).digest('hex');
    const responseBytes = new Uint8Array(gzip.byteLength);
    responseBytes.set(gzip);
    const fetcher = vi.fn().mockResolvedValue(new Response(responseBytes.buffer));

    const parsed = await fetchAndParseGmeOverlay('https://signed.invalid/artifact', sha, gzip.byteLength, fetcher);
    expect(parsed.duration_sec).toBe(5);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it('declared compressed size가 상한을 넘으면 body를 읽지 않고 거부한다', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('x', {
      headers: { 'content-length': String(MAX_GME_ARTIFACT_COMPRESSED_BYTES + 1) },
    }));
    await expect(fetchAndParseGmeOverlay(
      'https://signed.invalid/artifact', 'a'.repeat(64), 1, fetcher,
    )).rejects.toThrow(/large/i);
  });

  it('upstream 오류 원문을 parser 결과로 통과시키지 않는다', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('private provider error', { status: 500 }));
    await expect(fetchAndParseGmeOverlay(
      'https://signed.invalid/artifact', 'a'.repeat(64), 1, fetcher,
    )).rejects.toThrow('GME artifact fetch failed');
  });
});
