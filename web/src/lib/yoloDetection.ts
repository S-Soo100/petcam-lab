export type MediaKind = 'image' | 'video';
export type ProviderMode = 'fake' | 'worker';
export type ContributionStatus = 'not_requested' | 'candidate_only';
export type UsageScope =
  | 'labeling_bbox_assist_only'
  | 'owner_preview_bbox_suggestion_only';

export interface NormalizedBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Detection {
  label: 'gecko';
  confidence: number;
  bbox: NormalizedBox;
}

export interface DetectionFrame {
  frame_index: number;
  timestamp_ms: number;
  detections: Detection[];
}

export interface GeckoDetectionResult {
  request_id: string;
  media_kind: MediaKind;
  model_version: string;
  provider_mode: ProviderMode;
  processed_at: string;
  warning: string;
  frames: DetectionFrame[];
  contribution_status: ContributionStatus;
  threshold?: number;
  development_only?: true;
  usage_scope?: UsageScope;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function normalizedBox(value: unknown): NormalizedBox | null {
  if (!isRecord(value)) return null;
  const { x, y, width, height } = value;
  if (!finite(x) || !finite(y) || !finite(width) || !finite(height)) return null;
  if (x < 0 || y < 0 || width <= 0 || height <= 0) return null;
  if (x > 1 || y > 1 || x + width > 1 || y + height > 1) return null;
  return { x, y, width, height };
}

function detection(value: unknown): Detection | null {
  if (!isRecord(value) || value.label !== 'gecko' || !finite(value.confidence)) return null;
  if (value.confidence < 0 || value.confidence > 1) return null;
  const bbox = normalizedBox(value.bbox);
  if (!bbox) return null;
  return { label: 'gecko', confidence: value.confidence, bbox };
}

function frame(value: unknown): DetectionFrame | null {
  if (!isRecord(value)) return null;
  if (!Number.isInteger(value.frame_index) || (value.frame_index as number) < 0) return null;
  if (!finite(value.timestamp_ms) || value.timestamp_ms < 0) return null;
  if (!Array.isArray(value.detections) || value.detections.length > 100) return null;
  const detections: Detection[] = [];
  for (const item of value.detections) {
    const parsed = detection(item);
    if (!parsed) return null;
    detections.push(parsed);
  }
  return {
    frame_index: value.frame_index as number,
    timestamp_ms: value.timestamp_ms,
    detections,
  };
}

export function validateDetectionResult(value: unknown): GeckoDetectionResult | null {
  if (!isRecord(value)) return null;
  if (typeof value.request_id !== 'string' || value.request_id.length < 1 || value.request_id.length > 128) {
    return null;
  }
  if (value.media_kind !== 'image' && value.media_kind !== 'video') return null;
  if (typeof value.model_version !== 'string' || value.model_version.length < 1 || value.model_version.length > 128) {
    return null;
  }
  if (value.provider_mode !== 'fake' && value.provider_mode !== 'worker') return null;
  if (
    typeof value.processed_at !== 'string' ||
    value.processed_at.length > 64 ||
    Number.isNaN(Date.parse(value.processed_at))
  ) {
    return null;
  }
  if (typeof value.warning !== 'string' || value.warning.length < 1 || value.warning.length > 300) return null;
  if (
    value.contribution_status !== 'not_requested' &&
    value.contribution_status !== 'candidate_only'
  ) {
    return null;
  }
  if (!Array.isArray(value.frames) || value.frames.length < 1 || value.frames.length > 3600) return null;

  const hasAssistMetadata = value.threshold !== undefined
    || value.development_only !== undefined
    || value.usage_scope !== undefined;
  if (
    hasAssistMetadata
    && (
      !finite(value.threshold)
      || value.threshold < 0
      || value.threshold > 1
      || value.development_only !== true
      || (
        value.usage_scope !== 'labeling_bbox_assist_only'
        && value.usage_scope !== 'owner_preview_bbox_suggestion_only'
      )
    )
  ) return null;

  const frames: DetectionFrame[] = [];
  let previousIndex = -1;
  let previousTimestamp = -1;
  for (const item of value.frames) {
    const parsed = frame(item);
    if (!parsed) return null;
    if (parsed.frame_index <= previousIndex || parsed.timestamp_ms < previousTimestamp) return null;
    previousIndex = parsed.frame_index;
    previousTimestamp = parsed.timestamp_ms;
    frames.push(parsed);
  }

  const result: GeckoDetectionResult = {
    request_id: value.request_id,
    media_kind: value.media_kind,
    model_version: value.model_version,
    provider_mode: value.provider_mode,
    processed_at: value.processed_at,
    warning: value.warning,
    frames,
    contribution_status: value.contribution_status,
  };
  if (hasAssistMetadata) {
    result.threshold = value.threshold as number;
    result.development_only = true;
    result.usage_scope = value.usage_scope as UsageScope;
  }
  return result;
}

export function frameAtTime(
  frames: DetectionFrame[],
  timeMs: number,
  maxGapMs = 500,
): DetectionFrame | null {
  if (!Number.isFinite(timeMs) || timeMs < 0 || !Number.isFinite(maxGapMs) || maxGapMs < 0) {
    return null;
  }
  let found: DetectionFrame | null = null;
  for (const item of frames) {
    if (item.timestamp_ms > timeMs) break;
    found = item;
  }
  return found && timeMs - found.timestamp_ms <= maxGapMs ? found : null;
}
