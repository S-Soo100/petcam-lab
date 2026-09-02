export type OwnerCleanupDecision =
  | 'keep'
  | 'delete_gecko_absent'
  | 'delete_no_activity'
  | 'uncertain';

export interface OwnerCleanupItem {
  clip_id: string;
  started_at: string;
  duration_sec: number;
  camera_name: string;
}
export interface OwnerCleanupSummary {
  available: number;
  completed: number;
  remaining: number;
  source_missing: number;
}

export interface OwnerCleanupWorkspace {
  item: OwnerCleanupItem | null;
  summary: OwnerCleanupSummary;
}

export function mapOwnerCleanupRow(row: Record<string, unknown>): OwnerCleanupItem {
  return {
    clip_id: String(row.clip_id ?? ''),
    started_at: String(row.started_at ?? ''),
    duration_sec: Number(row.duration_sec ?? 0),
    camera_name: String(row.camera_name ?? ''),
  };
}

export function mapOwnerCleanupSummary(row: Record<string, unknown> | null): OwnerCleanupSummary {
  return {
    available: Number(row?.available ?? 0),
    completed: Number(row?.completed ?? 0),
    remaining: Number(row?.remaining ?? 0),
    source_missing: Number(row?.source_missing ?? 0),
  };
}
