import 'server-only';

import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';

import { parseGmeOverlayArtifact, type ParsedGmeOverlay } from './gmeOverlay';
import { ACTIVE_GME_DETECTOR_IDENTITY } from './gmeActiveIdentity';
import { supabaseAdmin } from './supabase';

export const MAX_GME_ARTIFACT_COMPRESSED_BYTES = 8 * 1024 * 1024;
export const MAX_GME_ARTIFACT_UNCOMPRESSED_BYTES = 32 * 1024 * 1024;

export interface CurrentGmeOverlaySource {
  runId: string;
  overlayRevision: string;
  artifactKey: string;
  artifactBytes: number;
}

export type CurrentGmeOverlayStatus =
  | { state: 'ready'; source: CurrentGmeOverlaySource }
  | { state: 'pending' }
  | { state: 'unavailable' };

function activeDetectorIdentity(): string {
  const identity = process.env.GME_ACTIVE_DETECTOR_IDENTITY ?? '';
  if (identity !== ACTIVE_GME_DETECTOR_IDENTITY) {
    throw new Error('invalid active GME detector identity');
  }
  return identity;
}

function assertSha(value: string): void {
  if (!/^[0-9a-f]{64}$/.test(value)) throw new Error('invalid GME artifact SHA');
}

export function parseGmeOverlayGzip(
  compressed: Uint8Array,
  expectedSha256: string,
  expectedBytes: number,
): ParsedGmeOverlay {
  assertSha(expectedSha256);
  if (!Number.isSafeInteger(expectedBytes) || expectedBytes <= 0) {
    throw new Error('invalid GME artifact byte count');
  }
  if (compressed.byteLength !== expectedBytes) throw new Error('GME artifact byte count mismatch');
  if (compressed.byteLength > MAX_GME_ARTIFACT_COMPRESSED_BYTES) {
    throw new Error('GME artifact is too large');
  }
  const actualSha = createHash('sha256').update(compressed).digest('hex');
  if (actualSha !== expectedSha256) throw new Error('GME artifact SHA mismatch');

  let raw: Buffer;
  try {
    raw = gunzipSync(compressed, { maxOutputLength: MAX_GME_ARTIFACT_UNCOMPRESSED_BYTES });
  } catch {
    throw new Error('invalid or oversized GME artifact gzip');
  }
  let payload: unknown;
  try {
    payload = JSON.parse(raw.toString('utf8'));
  } catch {
    throw new Error('invalid GME artifact JSON');
  }
  return parseGmeOverlayArtifact(payload);
}

async function readBounded(response: Response): Promise<Uint8Array> {
  if (!response.ok) throw new Error('GME artifact fetch failed');
  const declared = Number(response.headers.get('content-length'));
  if (Number.isFinite(declared) && declared > MAX_GME_ARTIFACT_COMPRESSED_BYTES) {
    throw new Error('GME artifact is too large');
  }
  if (!response.body) throw new Error('GME artifact body is missing');

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_GME_ARTIFACT_COMPRESSED_BYTES) {
        await reader.cancel();
        throw new Error('GME artifact is too large');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const joined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return joined;
}

export async function fetchAndParseGmeOverlay(
  signedUrl: string,
  expectedSha256: string,
  expectedBytes: number,
  fetcher: typeof fetch = fetch,
): Promise<ParsedGmeOverlay> {
  if (!signedUrl.startsWith('https://') && !signedUrl.startsWith('http://127.0.0.1:')) {
    throw new Error('invalid signed artifact URL');
  }
  const response = await fetcher(signedUrl, { cache: 'no-store', redirect: 'error' });
  const compressed = await readBounded(response);
  return parseGmeOverlayGzip(compressed, expectedSha256, expectedBytes);
}

export async function loadCurrentGmeOverlayStatus(
  clipId: string,
): Promise<CurrentGmeOverlayStatus> {
  const detectorIdentity = activeDetectorIdentity();
  const { data: jobs, error: jobError } = await supabaseAdmin
    .from('gme_jobs')
    .select('id, status, result_run_id, completed_at, created_at')
    .eq('clip_id', clipId)
    .eq('detector_identity', detectorIdentity)
    .order('completed_at', { ascending: false, nullsFirst: false })
    .order('created_at', { ascending: false })
    .order('id', { ascending: false })
    .limit(1);
  if (jobError) throw jobError;
  const job = (jobs ?? [])[0] as {
    id?: string;
    status?: string;
    result_run_id?: string | null;
  } | undefined;
  if (!job) return { state: 'pending' };
  if (job.status === 'queued' || job.status === 'processing' || job.status === 'failed_retryable') {
    return { state: 'pending' };
  }
  if (job.status !== 'succeeded' || !job.id || !job.result_run_id) {
    return { state: 'unavailable' };
  }

  const { data: runs, error: runError } = await supabaseAdmin
    .from('gme_runs')
    .select('id, permanent_artifact_key, permanent_artifact_sha256, permanent_artifact_bytes')
    .eq('id', job.result_run_id)
    .eq('job_id', job.id)
    .eq('clip_id', clipId)
    .eq('detector_identity', detectorIdentity)
    .eq('status', 'ok')
    .limit(1);
  if (runError) throw runError;
  const run = (runs ?? [])[0] as {
    id?: string;
    permanent_artifact_key?: string;
    permanent_artifact_sha256?: string;
    permanent_artifact_bytes?: number;
  } | undefined;
  if (!run) return { state: 'unavailable' };
  const artifactKey = run.permanent_artifact_key ?? '';
  const revision = run.permanent_artifact_sha256 ?? '';
  const artifactBytes = Number(run.permanent_artifact_bytes);
  if (
    typeof run.id !== 'string'
    || !artifactKey.startsWith('terra-derived/gme/v1/permanent/')
    || !/^[0-9a-f]{64}$/.test(revision)
    || !Number.isSafeInteger(artifactBytes)
    || artifactBytes <= 0
    || artifactBytes > MAX_GME_ARTIFACT_COMPRESSED_BYTES
  ) {
    throw new Error('current GME artifact provenance is invalid');
  }
  return {
    state: 'ready',
    source: {
      runId: run.id,
      overlayRevision: revision,
      artifactKey,
      artifactBytes,
    },
  };
}

export async function loadCurrentGmeOverlaySource(
  clipId: string,
): Promise<CurrentGmeOverlaySource | null> {
  const status = await loadCurrentGmeOverlayStatus(clipId);
  return status.state === 'ready' ? status.source : null;
}
