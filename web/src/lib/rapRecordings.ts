export type RapMode = 'test' | 'production';
export type RapCamera = 'cam01' | 'cam02' | 'cam03';
export type RapUploadStatus = 'pending' | 'uploading' | 'uploaded' | 'upload_failed' | 'integrity_conflict';

export type RapRecordingQuery = {
  mode: RapMode;
  camera?: RapCamera;
  night?: string;
  status?: RapUploadStatus;
  limit: number;
};

export type RapRecordingSummary = {
  id: string;
  mode: RapMode;
  camera_key: RapCamera;
  test_run_id: string | null;
  night_date: string | null;
  scheduled_start_utc: string;
  actual_start_utc: string;
  partial: boolean;
  duration_sec: number;
  codec: string;
  width: number;
  height: number;
  fps: number;
  video_size_bytes: number;
  capture_status: 'capturing' | 'captured' | 'capture_failed';
  upload_status: RapUploadStatus;
  last_error_code: string | null;
  uploaded_at: string | null;
};

const MODES = ['test', 'production'] as const;
const CAMERAS = ['cam01', 'cam02', 'cam03'] as const;
const STATUSES = ['pending', 'uploading', 'uploaded', 'upload_failed', 'integrity_conflict'] as const;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function parseRapRecordingQuery(search: URLSearchParams): RapRecordingQuery {
  const mode = search.get('mode') ?? 'production';
  const camera = search.get('camera');
  const night = search.get('night');
  const status = search.get('status');
  const rawLimit = search.get('limit');
  const limit = rawLimit === null ? 72 : Number(rawLimit);
  if (!MODES.includes(mode as RapMode)) throw new Error('잘못된 mode');
  if (camera !== null && !CAMERAS.includes(camera as RapCamera)) throw new Error('잘못된 camera');
  if (night !== null && (!DATE_RE.test(night) || Number.isNaN(Date.parse(`${night}T00:00:00Z`)))) {
    throw new Error('잘못된 night');
  }
  if (status !== null && !STATUSES.includes(status as RapUploadStatus)) throw new Error('잘못된 status');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('잘못된 limit');
  return {
    mode: mode as RapMode,
    ...(camera ? { camera: camera as RapCamera } : {}),
    ...(night ? { night } : {}),
    ...(status ? { status: status as RapUploadStatus } : {}),
    limit,
  };
}

export function toPublicRecording(row: Record<string, unknown>): RapRecordingSummary {
  return {
    id: String(row.id),
    mode: row.mode as RapMode,
    camera_key: row.camera_key as RapCamera,
    test_run_id: row.test_run_id === null ? null : String(row.test_run_id),
    night_date: row.night_date === null ? null : String(row.night_date),
    scheduled_start_utc: String(row.scheduled_start_utc),
    actual_start_utc: String(row.actual_start_utc),
    partial: Boolean(row.partial),
    duration_sec: Number(row.duration_sec),
    codec: String(row.codec),
    width: Number(row.width),
    height: Number(row.height),
    fps: Number(row.fps),
    video_size_bytes: Number(row.video_size_bytes),
    capture_status: row.capture_status as RapRecordingSummary['capture_status'],
    upload_status: row.upload_status as RapUploadStatus,
    last_error_code: row.last_error_code === null ? null : String(row.last_error_code),
    uploaded_at: row.uploaded_at === null ? null : String(row.uploaded_at),
  };
}

export function computeNightCoverage(rows: RapRecordingSummary[], cameraCount = 3) {
  if (!Number.isInteger(cameraCount) || cameraCount < 1 || cameraCount > 3) {
    throw new Error('cameraCount must be between 1 and 3');
  }
  const production = rows.filter((row) => row.mode === 'production');
  const unique = new Set(production.map((row) => `${row.camera_key}:${row.scheduled_start_utc}`));
  const uploaded = production.filter((row) => row.upload_status === 'uploaded').length;
  const failed = production.filter(
    (row) => row.capture_status === 'capture_failed' || ['upload_failed', 'integrity_conflict'].includes(row.upload_status),
  ).length;
  const expected = cameraCount * 24;
  return {
    expected,
    captured: unique.size,
    uploaded,
    failed,
    missing: Math.max(0, expected - unique.size),
  };
}
