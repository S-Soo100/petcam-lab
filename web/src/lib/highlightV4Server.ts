import 'server-only';

import { NextResponse } from 'next/server';

import {
  HIGHLIGHT_TRIGGERS,
  type HighlightCurrent,
  type HighlightFeatures,
  type HighlightInitial,
  type HighlightInitialStatus,
  type HighlightTrigger,
} from './highlightV4';

const STATUSES: readonly HighlightInitialStatus[] = ['decided', 'pending', 'failed'];
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface HighlightInitialRow {
  status: unknown; initial: unknown; rule_version: unknown; gme_run_id: unknown;
  reason: unknown; fired: unknown; shadow: unknown; features: unknown;
}
export interface HighlightCurrentRow {
  source: unknown; status: unknown; value: unknown; rule_version: unknown; reason: unknown;
  reviewer_id: unknown; decided_at: unknown; verdict_kind: unknown;
}

function triggers(v: unknown): HighlightTrigger[] {
  if (!Array.isArray(v)) throw new Error('invalid_highlight_initial');
  return v.map((t) => {
    if (typeof t !== 'string' || !(HIGHLIGHT_TRIGGERS as readonly string[]).includes(t)) throw new Error('invalid_highlight_initial');
    return t as HighlightTrigger;
  });
}

function num(v: unknown): number {
  const n = typeof v === 'string' ? Number(v) : v;
  if (typeof n !== 'number' || !Number.isFinite(n)) throw new Error('invalid_highlight_initial');
  return n;
}

function features(v: unknown): HighlightFeatures | null {
  if (v === null || v === undefined) return null;
  if (typeof v !== 'object') throw new Error('invalid_highlight_initial');
  const f = v as Record<string, unknown>;
  return {
    activity_sec: num(f.activity_sec),
    longest_moving_sec: num(f.longest_moving_sec),
    moving_burst_count: num(f.moving_burst_count),
    first_moving_sec: f.first_moving_sec === null || f.first_moving_sec === undefined ? null : num(f.first_moving_sec),
  };
}

export function mapHighlightInitialRow(row: HighlightInitialRow): HighlightInitial {
  const status = row.status;
  if (typeof status !== 'string' || !(STATUSES as readonly string[]).includes(status)) throw new Error('invalid_highlight_initial');
  if (typeof row.rule_version !== 'string' || typeof row.reason !== 'string') throw new Error('invalid_highlight_initial');
  const value = row.initial;
  if (status === 'decided' && typeof value !== 'boolean') throw new Error('invalid_highlight_initial');
  if (status !== 'decided' && value !== null) throw new Error('invalid_highlight_initial');
  return {
    status: status as HighlightInitialStatus,
    value: status === 'decided' ? (value as boolean) : null,
    rule_version: row.rule_version,
    reason: row.reason,
    fired: triggers(row.fired),
    shadow: triggers(row.shadow),
    features: status === 'decided' ? features(row.features) : null,
  };
}

export function mapHighlightCurrentRow(row: HighlightCurrentRow, reviewerName: string | null): HighlightCurrent {
  const source = row.source;
  const status = row.status;
  if (source !== 'human' && source !== 'rule') throw new Error('invalid_highlight_current');
  if (typeof status !== 'string' || !(STATUSES as readonly string[]).includes(status)) throw new Error('invalid_highlight_current');
  if (typeof row.rule_version !== 'string' || typeof row.reason !== 'string') throw new Error('invalid_highlight_current');
  if (row.value !== null && typeof row.value !== 'boolean') throw new Error('invalid_highlight_current');
  if (source === 'human') {
    if (typeof row.reviewer_id !== 'string' || !UUID_RE.test(row.reviewer_id)) throw new Error('invalid_highlight_current');
    if (typeof row.decided_at !== 'string') throw new Error('invalid_highlight_current');
    if (row.verdict_kind !== 'initial' && row.verdict_kind !== 'correction') throw new Error('invalid_highlight_current');
  }
  return {
    source,
    status: status as HighlightInitialStatus,
    value: row.value as boolean | null,
    rule_version: row.rule_version,
    reason: row.reason,
    reviewer_name: source === 'human' ? reviewerName : null,
    decided_at: source === 'human' ? (row.decided_at as string) : null,
    verdict_kind: source === 'human' ? (row.verdict_kind as 'initial' | 'correction') : null,
  };
}

// RPC 안정 SQLSTATE → HTTP. 나머지는 null 을 돌려 호출자가 502 로 접는다.
export function highlightRpcErrorResponse(error: unknown): NextResponse | null {
  const code = (error as { code?: string } | null)?.code;
  switch (code) {
    case '22023': return NextResponse.json({ detail: '요청 값이 잘못됐어.', code: 'invalid_request' }, { status: 400 });
    case 'P0002': return NextResponse.json({ detail: '영상을 찾을 수 없어.', code: 'not_found' }, { status: 404 });
    case 'PT403': return NextResponse.json({ detail: '이 작업을 할 권한이 없어.', code: 'forbidden' }, { status: 403 });
    case 'PT409': return NextResponse.json({ detail: '방금 다른 사람이 확정했어. 다음 영상으로 넘어가.', code: 'already_decided' }, { status: 409 });
    case 'PT428': return NextResponse.json({ detail: '활성 규칙이 없어. owner 에게 알려줘.', code: 'no_active_rule' }, { status: 503 });
    default: return null;
  }
}

export function highlightDatabaseError(cause: unknown): NextResponse {
  console.error('[labeling-v4] highlight database error', cause);
  return NextResponse.json({ detail: '잠시 후 다시 시도해.', code: 'database_unavailable' }, { status: 502 });
}
