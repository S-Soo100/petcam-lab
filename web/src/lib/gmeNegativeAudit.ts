export const AUDIT_VERDICTS = [
  'gecko_present',
  'gecko_absent',
  'uncertain',
  'media_error',
] as const;

export type AuditVerdict = (typeof AUDIT_VERDICTS)[number];

export interface NormalizedBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface AuditSubmission {
  verdict: AuditVerdict;
  representative_sec: number | null;
  bbox: NormalizedBox | null;
}

export interface AuditCorrection extends AuditSubmission {
  reason: string;
  revision: string;
}

export class AuditValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuditValidationError';
  }
}

const SUBMISSION_KEYS = ['bbox', 'representative_sec', 'verdict'] as const;
const CORRECTION_KEYS = ['bbox', 'reason', 'representative_sec', 'revision', 'verdict'] as const;
const BBOX_KEYS = ['height', 'width', 'x', 'y'] as const;
const VERDICT_SET = new Set<string>(AUDIT_VERDICTS);

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new AuditValidationError(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function requireExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new AuditValidationError(`${label} has invalid keys`);
  }
}

function requireFiniteSafeNumber(value: unknown, label: string): number {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    Math.abs(value) > Number.MAX_SAFE_INTEGER
  ) {
    throw new AuditValidationError(`${label} must be a finite safe number`);
  }
  return value;
}

function parseDbFiniteSafeNumber(value: unknown, label: string): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN;
  return requireFiniteSafeNumber(parsed, label);
}

function validateDuration(durationSec: number): number {
  const duration = requireFiniteSafeNumber(durationSec, 'duration_sec');
  if (duration <= 0) throw new AuditValidationError('duration_sec must be positive');
  return duration;
}

function validateNormalizedBox(value: unknown): NormalizedBox {
  const row = requireRecord(value, 'bbox');
  requireExactKeys(row, BBOX_KEYS, 'bbox');
  const box = {
    x: requireFiniteSafeNumber(row.x, 'bbox.x'),
    y: requireFiniteSafeNumber(row.y, 'bbox.y'),
    width: requireFiniteSafeNumber(row.width, 'bbox.width'),
    height: requireFiniteSafeNumber(row.height, 'bbox.height'),
  };
  if (
    box.x < 0 ||
    box.y < 0 ||
    box.width <= 0 ||
    box.height <= 0 ||
    box.x > 1 ||
    box.y > 1 ||
    box.x + box.width > 1 ||
    box.y + box.height > 1 ||
    !Number.isFinite(box.width * box.height) ||
    box.width * box.height <= 0
  ) {
    throw new AuditValidationError('bbox must have positive normalized area inside the frame');
  }
  return box;
}

export function validateAuditSubmission(value: unknown, durationSec: number): AuditSubmission {
  const duration = validateDuration(durationSec);
  const row = requireRecord(value, 'submission');
  requireExactKeys(row, SUBMISSION_KEYS, 'submission');
  if (typeof row.verdict !== 'string' || !VERDICT_SET.has(row.verdict)) {
    throw new AuditValidationError('invalid verdict');
  }
  const verdict = row.verdict as AuditVerdict;

  if (verdict !== 'gecko_present') {
    if (row.representative_sec !== null || row.bbox !== null) {
      throw new AuditValidationError('non-present verdict requires null geometry');
    }
    return { verdict, representative_sec: null, bbox: null };
  }

  const representativeSec = requireFiniteSafeNumber(
    row.representative_sec,
    'representative_sec',
  );
  if (representativeSec < 0 || representativeSec > duration) {
    throw new AuditValidationError('representative_sec is outside clip duration');
  }
  return {
    verdict,
    representative_sec: representativeSec,
    bbox: validateNormalizedBox(row.bbox),
  };
}

export function validateAuditCorrection(value: unknown, durationSec: number): AuditCorrection {
  const row = requireRecord(value, 'correction');
  requireExactKeys(row, CORRECTION_KEYS, 'correction');
  if (
    typeof row.reason !== 'string' ||
    row.reason.trim().length === 0 ||
    row.reason.trim().length > 2_000
  ) {
    throw new AuditValidationError('reason must be 1 to 2000 characters');
  }
  if (
    typeof row.revision !== 'string' ||
    row.revision.length === 0 ||
    row.revision.length > 256 ||
    row.revision.trim() !== row.revision
  ) {
    throw new AuditValidationError('revision is invalid');
  }
  const submission = validateAuditSubmission(
    {
      verdict: row.verdict,
      representative_sec: row.representative_sec,
      bbox: row.bbox,
    },
    durationSec,
  );
  return { ...submission, reason: row.reason.trim(), revision: row.revision };
}

export interface AuditQueueItem {
  item_id: string;
  ordinal: number;
  captured_at: string;
  duration_sec: number;
  media_ready: boolean;
  submitted: boolean;
}

export interface AuditQueueResponse {
  items: AuditQueueItem[];
  completed: number;
  total: number;
}

export interface AuditDetailItem extends Omit<AuditQueueItem, 'submitted'> {
  initial_verdict: AuditVerdict | null;
  initial_representative_sec: number | null;
  initial_bbox: NormalizedBox | null;
  effective_verdict: AuditVerdict | null;
  effective_representative_sec: number | null;
  effective_bbox: NormalizedBox | null;
  revision: string | null;
}

function mapCommonRow(row: Record<string, unknown>) {
  if (typeof row.item_id !== 'string' || row.item_id.length === 0) {
    throw new AuditValidationError('invalid item_id');
  }
  const ordinal = requireFiniteSafeNumber(row.ordinal, 'ordinal');
  if (!Number.isSafeInteger(ordinal) || ordinal < 1) {
    throw new AuditValidationError('invalid ordinal');
  }
  if (typeof row.captured_at !== 'string' || row.captured_at.length === 0) {
    throw new AuditValidationError('invalid captured_at');
  }
  const durationSec = validateDuration(parseDbFiniteSafeNumber(row.duration_sec, 'duration_sec'));
  if (typeof row.media_ready !== 'boolean') {
    throw new AuditValidationError('invalid media_ready');
  }
  return {
    item_id: row.item_id,
    ordinal,
    captured_at: row.captured_at,
    duration_sec: durationSec,
    media_ready: row.media_ready,
  };
}

export function mapAuditQueueRow(value: unknown): AuditQueueItem {
  const row = requireRecord(value, 'queue row');
  if (typeof row.submitted !== 'boolean') {
    throw new AuditValidationError('invalid submitted');
  }
  return { ...mapCommonRow(row), submitted: row.submitted };
}

function mapVerdictFields(
  row: Record<string, unknown>,
  prefix: 'initial' | 'effective',
  durationSec: number,
): Pick<AuditDetailItem,
  | `${typeof prefix}_verdict`
  | `${typeof prefix}_representative_sec`
  | `${typeof prefix}_bbox`
> {
  const verdictKey = `${prefix}_verdict` as const;
  const representativeKey = `${prefix}_representative_sec` as const;
  const bboxKey = `${prefix}_bbox` as const;
  if (row[verdictKey] === null) {
    if (row[representativeKey] !== null || row[bboxKey] !== null) {
      throw new AuditValidationError(`invalid ${prefix} verdict fields`);
    }
    return {
      [verdictKey]: null,
      [representativeKey]: null,
      [bboxKey]: null,
    } as Pick<AuditDetailItem,
      | `${typeof prefix}_verdict`
      | `${typeof prefix}_representative_sec`
      | `${typeof prefix}_bbox`>;
  }
  const parsed = validateAuditSubmission(
    {
      verdict: row[verdictKey],
      representative_sec:
        row[representativeKey] === null
          ? null
          : parseDbFiniteSafeNumber(row[representativeKey], representativeKey),
      bbox: row[bboxKey],
    },
    durationSec,
  );
  return {
    [verdictKey]: parsed.verdict,
    [representativeKey]: parsed.representative_sec,
    [bboxKey]: parsed.bbox,
  } as Pick<AuditDetailItem,
    | `${typeof prefix}_verdict`
    | `${typeof prefix}_representative_sec`
    | `${typeof prefix}_bbox`>;
}

export function mapAuditDetailRow(value: unknown): AuditDetailItem {
  const row = requireRecord(value, 'detail row');
  const common = mapCommonRow(row);
  const initial = mapVerdictFields(row, 'initial', common.duration_sec);
  const effective = mapVerdictFields(row, 'effective', common.duration_sec);
  const revision = row.revision;
  if (revision !== null && (typeof revision !== 'string' || revision.length === 0)) {
    throw new AuditValidationError('invalid revision');
  }
  if ((initial.initial_verdict === null) !== (revision === null)) {
    throw new AuditValidationError('revision must match own submission state');
  }
  return { ...common, ...initial, ...effective, revision };
}
