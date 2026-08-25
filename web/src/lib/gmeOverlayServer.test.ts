import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';

import { describe, expect, it, vi } from 'vitest';

import {
  fetchAndParseGmeOverlay,
  MAX_GME_ARTIFACT_COMPRESSED_BYTES,
  parseGmeOverlayGzip,
} from './gmeOverlayServer';

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
