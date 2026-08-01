import 'server-only';

import { NextResponse } from 'next/server';
import type { AccessStatus } from './labelingAccess';

export const BOUNDARY_DECISIONS = [
  'same_event',
  'different_event',
  'uncertain',
] as const;
export type BoundaryDecision = (typeof BOUNDARY_DECISIONS)[number];

export const BOUNDARY_ELIGIBILITY_DECISIONS = [
  'eligible',
  'left_gecko_absent',
  'right_gecko_absent',
  'both_gecko_absent',
  'capture_or_media_error',
] as const;
export type BoundaryEligibilityDecision = (typeof BOUNDARY_ELIGIBILITY_DECISIONS)[number];

export interface BoundaryClipSummary {
  clip_id: string;
  started_at: string;
  duration_sec: number;
  camera_name: string | null;
}

export interface BoundaryPairSummary {
  pair_id: string;
  ordinal: number;
  gap_sec: number;
  gap_bin: 'le30' | '30to60' | '60to300';
  left: BoundaryClipSummary;
  right: BoundaryClipSummary;
}

export interface BoundaryWorkspace {
  enabled: boolean;
  mode: 'eligibility' | 'boundary' | 'waiting';
  reviewer_role: 'owner' | 'peer' | null;
  split: 'development' | 'holdout' | null;
  total: number;
  completed: number;
  next_pair: BoundaryPairSummary | null;
}

export interface LabelingDataDashboard {
  video_record_count: number;
  playable_video_count: number;
  gt_labeled_video_count: number;
  behavior_counts: Record<string, number>;
  generated_at: string;
}

export interface BoundaryConflict {
  pair_id: string;
  ordinal: number;
  split: 'development' | 'holdout';
  gap_sec: number;
  gap_bin: 'le30' | '30to60' | '60to300';
  submissions: { reviewer_role: 'owner' | 'peer'; decision: BoundaryDecision }[];
}

export interface BoundaryConflicts {
  items: BoundaryConflict[];
  total: number;
}

type Rpc = (
  fn: string,
  args: Record<string, unknown>,
) => PromiseLike<{ data: unknown; error: { message?: string } | null }>;

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('invalid RPC response');
  }
  return value as Record<string, unknown>;
}

function nonnegativeInt(value: unknown, field: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`invalid ${field}`);
  }
  return value as number;
}

function finiteNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new Error(`invalid ${field}`);
  }
  return value;
}

function clip(value: unknown): BoundaryClipSummary {
  const row = record(value);
  if (
    typeof row.clip_id !== 'string' || !row.clip_id ||
    typeof row.started_at !== 'string' || Number.isNaN(Date.parse(row.started_at)) ||
    (row.camera_name !== null && typeof row.camera_name !== 'string')
  ) throw new Error('invalid boundary clip');
  return {
    clip_id: row.clip_id,
    started_at: row.started_at,
    duration_sec: finiteNumber(row.duration_sec, 'duration_sec'),
    camera_name: row.camera_name,
  };
}

export function isBoundaryDecision(value: unknown): value is BoundaryDecision {
  return BOUNDARY_DECISIONS.includes(value as BoundaryDecision);
}

export function isBoundaryEligibilityDecision(value: unknown): value is BoundaryEligibilityDecision {
  return BOUNDARY_ELIGIBILITY_DECISIONS.includes(value as BoundaryEligibilityDecision);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function isBoundaryUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID.test(value);
}

export function boundaryRpcErrorResponse(error: { code?: string } | null): NextResponse | null {
  if (!error?.code) return null;
  if (error.code === '22023') {
    return NextResponse.json({ detail: '입력값이 올바르지 않아.' }, { status: 400 });
  }
  if (error.code === 'PT403') {
    return NextResponse.json({ detail: '대상을 찾을 수 없어.' }, { status: 404 });
  }
  if (error.code === 'PT409') {
    return NextResponse.json({ detail: '현재 열려 있는 검수가 아니야.' }, { status: 409 });
  }
  if (error.code === 'PT410') {
    return NextResponse.json({ detail: '이미 제출되어 바꿀 수 없어.' }, { status: 409 });
  }
  return null;
}

export async function getBoundaryEnabled(
  userId: string,
  status: AccessStatus,
  rpc: Rpc,
): Promise<boolean> {
  if (status !== 'owner' && status !== 'labeler') return false;
  const { data, error } = await rpc('fn_get_rba_boundary_access', {
    p_reviewer_id: userId,
  });
  if (error) throw new Error(`boundary access: ${error.message ?? 'database error'}`);
  return record(data).enabled === true;
}

export function mapBoundaryWorkspace(value: unknown): BoundaryWorkspace {
  const row = record(value);
  const reviewerRole = row.reviewer_role;
  const split = row.split;
  const mode = row.mode;
  if (
    typeof row.enabled !== 'boolean' ||
    (mode !== 'eligibility' && mode !== 'boundary' && mode !== 'waiting') ||
    (reviewerRole !== null && reviewerRole !== 'owner' && reviewerRole !== 'peer') ||
    (split !== null && split !== 'development' && split !== 'holdout')
  ) throw new Error('invalid boundary workspace');

  let nextPair: BoundaryPairSummary | null = null;
  if (row.next_pair !== null) {
    const pair = record(row.next_pair);
    if (
      typeof pair.pair_id !== 'string' || !pair.pair_id ||
      !['le30', '30to60', '60to300'].includes(String(pair.gap_bin))
    ) throw new Error('invalid boundary pair');
    nextPair = {
      pair_id: pair.pair_id,
      ordinal: nonnegativeInt(pair.ordinal, 'ordinal'),
      gap_sec: finiteNumber(pair.gap_sec, 'gap_sec'),
      gap_bin: pair.gap_bin as BoundaryPairSummary['gap_bin'],
      left: clip(pair.left),
      right: clip(pair.right),
    };
  }

  const total = nonnegativeInt(row.total, 'total');
  const completed = nonnegativeInt(row.completed, 'completed');
  if (completed > total) throw new Error('invalid boundary progress');
  return {
    enabled: row.enabled,
    mode,
    reviewer_role: reviewerRole,
    split,
    total,
    completed,
    next_pair: nextPair,
  };
}

export function mapLabelingDashboard(value: unknown): LabelingDataDashboard {
  const row = record(value);
  const behaviorRaw = record(row.behavior_counts);
  const behaviorCounts: Record<string, number> = {};
  for (const [key, count] of Object.entries(behaviorRaw)) {
    if (!key || !Number.isInteger(count) || (count as number) < 0) {
      throw new Error('invalid behavior_counts');
    }
    behaviorCounts[key] = count as number;
  }
  const gtCount = nonnegativeInt(row.gt_labeled_video_count, 'gt_labeled_video_count');
  const behaviorTotal = Object.values(behaviorCounts).reduce((sum, count) => sum + count, 0);
  if (behaviorTotal !== gtCount) throw new Error('dashboard denominator mismatch');
  if (typeof row.generated_at !== 'string' || Number.isNaN(Date.parse(row.generated_at))) {
    throw new Error('invalid generated_at');
  }
  return {
    video_record_count: nonnegativeInt(row.video_record_count, 'video_record_count'),
    playable_video_count: nonnegativeInt(row.playable_video_count, 'playable_video_count'),
    gt_labeled_video_count: gtCount,
    behavior_counts: behaviorCounts,
    generated_at: row.generated_at,
  };
}

export function mapBoundaryConflicts(value: unknown): BoundaryConflicts {
  const row = record(value);
  if (!Array.isArray(row.items)) throw new Error('invalid conflict items');
  const items = row.items.map((raw): BoundaryConflict => {
    const item = record(raw);
    if (
      typeof item.pair_id !== 'string' || !item.pair_id ||
      (item.split !== 'development' && item.split !== 'holdout') ||
      !['le30', '30to60', '60to300'].includes(String(item.gap_bin)) ||
      !Array.isArray(item.submissions) || item.submissions.length !== 2
    ) throw new Error('invalid conflict');
    const submissions: BoundaryConflict['submissions'] = item.submissions.map((rawSubmission) => {
      const submission = record(rawSubmission);
      if (
        (submission.reviewer_role !== 'owner' && submission.reviewer_role !== 'peer') ||
        !isBoundaryDecision(submission.decision)
      ) throw new Error('invalid conflict submission');
      return {
        reviewer_role: submission.reviewer_role as 'owner' | 'peer',
        decision: submission.decision,
      };
    });
    return {
      pair_id: item.pair_id,
      ordinal: nonnegativeInt(item.ordinal, 'ordinal'),
      split: item.split,
      gap_sec: finiteNumber(item.gap_sec, 'gap_sec'),
      gap_bin: item.gap_bin as BoundaryConflict['gap_bin'],
      submissions,
    };
  });
  const total = nonnegativeInt(row.total, 'total');
  if (total !== items.length) throw new Error('conflict total mismatch');
  return { items, total };
}
