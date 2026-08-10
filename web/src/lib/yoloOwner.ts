import { mapBlindWorkspace, parseHumanAnnotation, type BlindTask, type HumanAnnotation } from './yoloContribution';
import { validateDetectionResult, type GeckoDetectionResult } from './yoloDetection';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface YoloOwnerReview {
  revision_id: string;
  task: BlindTask;
  blind_annotation: HumanAnnotation;
  revision_annotation: HumanAnnotation;
  revision_reason: string;
  prediction: GeckoDetectionResult;
}

export interface YoloOwnerOverview {
  reviews: YoloOwnerReview[];
  datasets: { id: string; version: string }[];
  models: { version: string; fixed_test_passed: boolean; future_holdout_passed: boolean; owner_approved: boolean; active: boolean }[];
  active_model_version: string | null;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('invalid yolo owner overview');
  return value as Record<string, unknown>;
}

export function mapYoloOwnerOverview(value: unknown): YoloOwnerOverview {
  const raw = record(value);
  if (!Array.isArray(raw.reviews) || !Array.isArray(raw.datasets) || !Array.isArray(raw.models)) throw new Error('invalid yolo owner overview');
  const reviews = raw.reviews.map((item): YoloOwnerReview => {
    const row = record(item);
    if (typeof row.revision_id !== 'string' || !UUID.test(row.revision_id)) throw new Error('invalid yolo owner review');
    const task = mapBlindWorkspace({
      enabled: true, total: 1, completed: 0,
      next_task: { task_id: row.task_id, media_kind: row.media_kind, media_url: row.media_url, frame_manifest: row.frame_manifest, stage: 'revealed' },
    }).next_task;
    const blind = parseHumanAnnotation({ boxes: row.blind_boxes, no_gecko: row.blind_no_gecko });
    const revision = parseHumanAnnotation({ boxes: row.revision_boxes, no_gecko: row.revision_no_gecko });
    const prediction = validateDetectionResult(row.prediction);
    if (!task || !blind || !revision || !prediction || typeof row.revision_reason !== 'string') throw new Error('invalid yolo owner review');
    return { revision_id: row.revision_id.toLowerCase(), task, blind_annotation: blind, revision_annotation: revision, revision_reason: row.revision_reason, prediction };
  });
  const datasets = raw.datasets.map((item) => {
    const row = record(item);
    if (typeof row.id !== 'string' || !UUID.test(row.id) || typeof row.version !== 'string') throw new Error('invalid yolo dataset');
    return { id: row.id.toLowerCase(), version: row.version };
  });
  const models = raw.models.map((item) => {
    const row = record(item);
    if (typeof row.version !== 'string' || typeof row.fixed_test_passed !== 'boolean' || typeof row.future_holdout_passed !== 'boolean' || typeof row.owner_approved !== 'boolean' || typeof row.active !== 'boolean') throw new Error('invalid yolo model');
    return { version: row.version, fixed_test_passed: row.fixed_test_passed, future_holdout_passed: row.future_holdout_passed, owner_approved: row.owner_approved, active: row.active };
  });
  if (raw.active_model_version !== null && typeof raw.active_model_version !== 'string') throw new Error('invalid active model');
  return { reviews, datasets, models, active_model_version: raw.active_model_version as string | null };
}
