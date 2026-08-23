import { NextRequest } from 'next/server';

import { validateAuditSubmission } from '@/lib/gmeNegativeAudit';
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

const KEYS = ['bbox', 'expected_submission_digest', 'final_verdict', 'reason', 'representative_sec'] as const;
const SHA256 = /^[0-9a-f]{64}$/;

function exactRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('shape');
  const row = value as Record<string, unknown>;
  const actual = Object.keys(row).sort();
  const expected = [...KEYS].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) throw new Error('keys');
  return row;
}

function reason(value: unknown): string {
  if (typeof value !== 'string' || value !== value.trim() || value.length < 1 || value.length > 2_000) throw new Error('reason');
  return value;
}

function digest(value: unknown): string {
  if (typeof value !== 'string' || !SHA256.test(value)) throw new Error('digest');
  return value;
}

function firstRow(value: unknown): Record<string, unknown> | null {
  const row = Array.isArray(value) ? value[0] : value;
  return typeof row === 'object' && row !== null && !Array.isArray(row) ? row as Record<string, unknown> : null;
}

function ownerError(code: unknown) {
  switch (String(code ?? '')) {
    case '22023': return auditInvalid();
    case 'PT403': return auditJson({ detail: 'Owner 권한이 없어.', code: 'owner_forbidden' }, 403);
    case 'PT404': return auditJson({ detail: '대상을 찾을 수 없어.', code: 'not_found' }, 404);
    case 'PT409': return auditJson({ detail: '판정이 변경됐어. 새로고침 후 다시 확인해.', code: 'stale_revision' }, 409);
    case 'PT410': return auditJson({ detail: '이미 Owner 판정이 완료됐어.', code: 'already_adjudicated' }, 410);
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
  let adjudication;
  let expectedDigest: string;
  let adjudicationReason: string;
  try {
    const row = exactRecord(body.value);
    adjudication = validateAuditSubmission({
      verdict: row.final_verdict,
      representative_sec: row.representative_sec,
      bbox: row.bbox,
    }, Number.MAX_SAFE_INTEGER);
    expectedDigest = digest(row.expected_submission_digest);
    adjudicationReason = reason(row.reason);
  } catch {
    return auditInvalid();
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_append_gme_negative_audit_adjudication', {
      p_item_id: params.itemId,
      p_owner_id: access.userId,
      p_final_verdict: adjudication.verdict,
      p_representative_sec: adjudication.representative_sec,
      p_bbox: adjudication.bbox,
      p_reason: adjudicationReason,
      p_expected_submission_digest: expectedDigest,
    });
    if (error) return ownerError(error.code);
    const result = firstRow(data);
    if (
      !result || Object.keys(result).sort().join(',') !== 'adjudication_id,digest,status' ||
      result.status !== 'adjudicated' || typeof result.adjudication_id !== 'string'
    ) return auditUnavailable();
    return auditJson({ status: 'adjudicated', effective_digest: digest(result.digest) });
  } catch {
    return auditUnavailable();
  }
}
