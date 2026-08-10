import {
  validateDetectionResult,
  type GeckoDetectionResult,
  type NormalizedBox,
} from './yoloDetection';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface HumanBox {
  frame_index: number;
  bbox: NormalizedBox;
}

export interface HumanAnnotation {
  boxes: HumanBox[];
  no_gecko: boolean;
}

export interface ContributionFrame {
  frame_index: number;
  timestamp_ms: number;
}

export interface BlindTask {
  task_id: string;
  media_kind: 'image' | 'video';
  media_url: string;
  frame_manifest: ContributionFrame[];
  stage: 'blind' | 'submitted' | 'revealed';
}

export interface BlindWorkspace {
  enabled: boolean;
  total: number;
  completed: number;
  next_task: BlindTask | null;
}

export interface RevealResult {
  task_id: string;
  revealed_at: string;
  prediction: GeckoDetectionResult;
  blind_annotation: HumanAnnotation;
  working_annotation: HumanAnnotation;
  owner_feedback: string | null;
  stage: 'revealed';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function parseBox(value: unknown): NormalizedBox | null {
  if (!isRecord(value)) return null;
  const { x, y, width, height } = value;
  if (!finite(x) || !finite(y) || !finite(width) || !finite(height)) return null;
  if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > 1 || y + height > 1) {
    return null;
  }
  return { x, y, width, height };
}

export function parseHumanAnnotation(value: unknown): HumanAnnotation | null {
  if (!isRecord(value) || !Array.isArray(value.boxes) || typeof value.no_gecko !== 'boolean') {
    return null;
  }
  if (value.boxes.length > 100) return null;
  const boxes: HumanBox[] = [];
  for (const item of value.boxes) {
    if (!isRecord(item) || !Number.isInteger(item.frame_index) || (item.frame_index as number) < 0) {
      return null;
    }
    const bbox = parseBox(item.bbox);
    if (!bbox) return null;
    boxes.push({ frame_index: item.frame_index as number, bbox });
  }
  if (value.no_gecko !== (boxes.length === 0)) return null;
  return { boxes, no_gecko: value.no_gecko };
}

function parseFrameManifest(value: unknown): ContributionFrame[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 3600) return null;
  const frames: ContributionFrame[] = [];
  let previousIndex = -1;
  let previousTimestamp = -1;
  for (const item of value) {
    if (!isRecord(item) || !Number.isInteger(item.frame_index) || (item.frame_index as number) < 0) return null;
    if (!finite(item.timestamp_ms) || item.timestamp_ms < 0) return null;
    if ((item.frame_index as number) <= previousIndex || item.timestamp_ms < previousTimestamp) return null;
    previousIndex = item.frame_index as number;
    previousTimestamp = item.timestamp_ms;
    frames.push({ frame_index: previousIndex, timestamp_ms: item.timestamp_ms });
  }
  return frames;
}

function parseBlindTask(value: unknown): BlindTask | null {
  if (!isRecord(value) || typeof value.task_id !== 'string' || !UUID.test(value.task_id)) return null;
  if (value.media_kind !== 'image' && value.media_kind !== 'video') return null;
  if (typeof value.media_url !== 'string' || value.media_url.length < 1 || value.media_url.length > 2000) return null;
  if (value.stage !== 'blind' && value.stage !== 'submitted' && value.stage !== 'revealed') return null;
  const frameManifest = parseFrameManifest(value.frame_manifest);
  if (!frameManifest) return null;
  return {
    task_id: value.task_id.toLowerCase(),
    media_kind: value.media_kind,
    media_url: value.media_url,
    frame_manifest: frameManifest,
    stage: value.stage,
  };
}

export function mapBlindWorkspace(value: unknown): BlindWorkspace {
  if (!isRecord(value) || typeof value.enabled !== 'boolean') throw new Error('invalid yolo workspace');
  if (!Number.isInteger(value.total) || (value.total as number) < 0) throw new Error('invalid yolo workspace');
  if (!Number.isInteger(value.completed) || (value.completed as number) < 0) throw new Error('invalid yolo workspace');
  const nextTask = value.next_task === null ? null : parseBlindTask(value.next_task);
  if (value.next_task !== null && !nextTask) throw new Error('invalid yolo workspace');
  return {
    enabled: value.enabled,
    total: value.total as number,
    completed: value.completed as number,
    next_task: nextTask,
  };
}

export function mapRevealResult(value: unknown): RevealResult {
  if (!isRecord(value) || typeof value.task_id !== 'string' || !UUID.test(value.task_id)) {
    throw new Error('invalid yolo reveal');
  }
  if (typeof value.revealed_at !== 'string' || Number.isNaN(Date.parse(value.revealed_at))) {
    throw new Error('invalid yolo reveal');
  }
  const prediction = validateDetectionResult(value.prediction);
  const blindAnnotation = parseHumanAnnotation({
    boxes: value.blind_boxes,
    no_gecko: value.blind_no_gecko,
  });
  const workingAnnotation = parseHumanAnnotation({
    boxes: value.working_boxes ?? value.blind_boxes,
    no_gecko: value.working_no_gecko ?? value.blind_no_gecko,
  });
  const ownerFeedback = value.owner_feedback === null || value.owner_feedback === undefined
    ? null
    : typeof value.owner_feedback === 'string' && value.owner_feedback.length <= 1000
      ? value.owner_feedback
      : undefined;
  if (!prediction || !blindAnnotation || !workingAnnotation || ownerFeedback === undefined || value.stage !== 'revealed') {
    throw new Error('invalid yolo reveal');
  }
  return {
    task_id: value.task_id.toLowerCase(),
    revealed_at: value.revealed_at,
    prediction,
    blind_annotation: blindAnnotation,
    working_annotation: workingAnnotation,
    owner_feedback: ownerFeedback,
    stage: 'revealed',
  };
}

export function isYoloUuid(value: string): boolean {
  return UUID.test(value);
}
