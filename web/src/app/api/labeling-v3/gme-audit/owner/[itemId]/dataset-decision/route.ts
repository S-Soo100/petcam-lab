import { NextRequest } from 'next/server';

import {
  auditInvalid,
  auditJson,
  auditUnavailable,
  isValidAuditItemId,
  readAuditJsonBody,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const KEYS = ['decision', 'expected_effective_digest', 'reason'] as const;
const DECISIONS = new Set(['include_candidate', 'exclude_duplicate', 'exclude_holdout', 'exclude_quality', 'defer']);
const SHA256 = /^[0-9a-f]{64}$/;

function exactRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('shape');
  const row = value as Record<string, unknown>;
  const actual = Object.keys(row).sort();
  const expected = [...KEYS].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new Error('keys');
  return row;
}

function firstStatus(value: unknown): string | null {
  const row = Array.isArray(value) ? value[0] : value;
  return typeof row === 'object' && row !== null && (row as { status?: unknown }).status === 'decided' ? 'decided' : null;
}

function ownerError(code: unknown) {
  switch (String(code ?? '')) {
    case '22023': return auditInvalid();
    case 'PT403': return auditJson({ detail: 'Owner 권한이 없어.', code: 'owner_forbidden' }, 403);
    case 'PT404': return auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404);
    case 'PT409': return auditJson({ detail: '현재 판정으로는 이 결정을 저장할 수 없어. 새로고침해.', code: 'stale_or_ineligible' }, 409);
    case 'PT410': return auditJson({ detail: '이미 처리된 결정이야.', code: 'already_decided' }, 410);
    case 'PT427': return auditJson({ detail: '점검이 종료됐어.', code: 'batch_closed' }, 410);
    default: return auditUnavailable();
  }
}

export async function POST(req: NextRequest, { params }: { params: { itemId: string } }) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (!access.isOwner) return auditJson({ detail: 'Owner만 접근할 수 있어.', code: 'owner_required' }, 403);
  if (!isValidAuditItemId(params.itemId) || Array.from(req.nextUrl.searchParams.keys()).length > 0) return auditInvalid();

  const body = await readAuditJsonBody(req);
  if (!body.ok) return body.response;
  let decision: string;
  let decisionReason: string;
  let expectedDigest: string;
  try {
    const row = exactRecord(body.value);
    if (typeof row.decision !== 'string' || !DECISIONS.has(row.decision)) throw new Error('decision');
    if (typeof row.reason !== 'string' || row.reason !== row.reason.trim() || row.reason.length < 1 || row.reason.length > 2_000) throw new Error('reason');
    if (typeof row.expected_effective_digest !== 'string' || !SHA256.test(row.expected_effective_digest)) throw new Error('digest');
    decision = row.decision;
    decisionReason = row.reason;
    expectedDigest = row.expected_effective_digest;
  } catch {
    return auditInvalid();
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_append_gme_negative_audit_dataset_decision', {
      p_item_id: params.itemId,
      p_owner_id: access.userId,
      p_decision: decision,
      p_reason: decisionReason,
      p_expected_effective_digest: expectedDigest,
    });
    if (error) return ownerError(error.code);
    if (firstStatus(data) !== 'decided') return auditUnavailable();
    return auditJson({ status: 'decided' });
  } catch {
    return auditUnavailable();
  }
}
