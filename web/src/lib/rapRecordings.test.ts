import { describe, expect, it } from 'vitest';

import { computeNightCoverage, parseRapRecordingQuery, toPublicRecording } from './rapRecordings';

const row = {
  id: '380d97fd-0000-4000-8000-000000000001',
  mode: 'production',
  camera_key: 'cam01',
  test_run_id: null,
  night_date: '2026-08-26',
  scheduled_start_utc: '2026-08-26T11:00:00Z',
  actual_start_utc: '2026-08-26T11:00:01Z',
  partial: false,
  duration_sec: 1800,
  codec: 'hevc',
  width: 2880,
  height: 1620,
  fps: 20,
  video_size_bytes: 380_000_000,
  capture_status: 'captured',
  upload_status: 'uploaded',
  last_error_code: null,
  uploaded_at: '2026-08-26T11:31:00Z',
  video_r2_key: 'c500g/secret/video.mp4',
  thumbnail_r2_key: 'c500g/secret/thumbnail.jpg',
  log_r2_key: 'c500g/secret/log',
  manifest_r2_key: 'c500g/secret/manifest.json',
  video_sha256: 'a'.repeat(64),
  relative_bundle_path: 'c500g/local/private',
};

describe('RAP recording public contract', () => {
  it('parses strict allowlisted filters and bounds', () => {
    const query = parseRapRecordingQuery(
      new URLSearchParams('mode=production&camera=cam02&night=2026-08-26&status=uploaded&limit=50'),
    );
    expect(query).toEqual({ mode: 'production', camera: 'cam02', night: '2026-08-26', status: 'uploaded', limit: 50 });
  });

  it.each(['camera=cam04', 'night=26-08-2026', 'limit=0', 'limit=101', 'status=unknown'])(
    'rejects invalid query %s',
    (raw) => expect(() => parseRapRecordingQuery(new URLSearchParams(raw))).toThrow(),
  );

  it('removes object keys, hashes and local paths from the public summary', () => {
    const publicRow = toPublicRecording(row);
    const encoded = JSON.stringify(publicRow);
    expect(publicRow.camera_key).toBe('cam01');
    expect(encoded).not.toContain('r2_key');
    expect(encoded).not.toContain('sha256');
    expect(encoded).not.toContain('relative_bundle_path');
    expect(encoded).not.toContain('c500g/secret');
  });

  it('computes 72 expected production slots without counting failures as missing', () => {
    const rows = Array.from({ length: 72 }, (_, index) => ({
      ...toPublicRecording(row),
      id: `id-${index}`,
      camera_key: `cam0${Math.floor(index / 24) + 1}` as 'cam01' | 'cam02' | 'cam03',
      scheduled_start_utc: new Date(Date.UTC(2026, 7, 26, 11, index * 30)).toISOString(),
      upload_status: index === 71 ? 'upload_failed' as const : 'uploaded' as const,
    }));
    expect(computeNightCoverage(rows)).toEqual({ expected: 72, captured: 72, uploaded: 71, failed: 1, missing: 0 });
  });

  it('uses 24 expected slots when one camera is selected', () => {
    const one = [toPublicRecording(row)];
    expect(computeNightCoverage(one, 1)).toMatchObject({ expected: 24, captured: 1, missing: 23 });
  });
});
