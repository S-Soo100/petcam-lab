import { NextRequest } from 'next/server';

import { validateAuditCorrection } from '@/lib/gmeNegativeAudit';
import {
  auditInvalid,
  auditJson,
  auditNotAssigned,
  auditUnavailable,
  mapAuditRpcError,
  readAuditJsonBody,
  requireAuditAssignment,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function firstStatus(value: unknown): string | null {
  const row = Array.isArray(value) ? value[0] : value;
  return typeof row === 'object' && row !== null && typeof (row as { status?: unknown }).status === 'string'
    ? ((row as { status: string }).status)
    : null;
}

export async function POST(
  req: NextRequest,
  { params }: { params: { itemId: string } },
) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (Array.from(req.nextUrl.searchParams.keys()).length > 0) return auditInvalid();

  const body = await readAuditJsonBody(req);
  if (!body.ok) return body.response;

  // public shape is independent of assignment state; actual duration is checked again below.
  try {
    validateAuditCorrection(body.value, Number.MAX_SAFE_INTEGER);
  } catch {
    return auditInvalid();
  }

  const assigned = await requireAuditAssignment(access.userId, params.itemId);
  if (!assigned.ok) return withAuditNoStore(assigned.response);
  if (assigned.row.initial_verdict === null) return auditNotAssigned();

  let correction;
  try {
    correction = validateAuditCorrection(body.value, Number(assigned.row.duration_sec));
  } catch {
    return auditInvalid();
  }

  try {
    const { data, error } = await supabaseAdmin.rpc(
      'fn_append_gme_negative_audit_correction',
      {
        p_item_id: params.itemId,
        p_reviewer_id: access.userId,
        p_verdict: correction.verdict,
        p_representative_sec: correction.representative_sec,
        p_bbox: correction.bbox,
        p_reason: correction.reason,
        // public wire의 opaque revision을 DB optimistic-concurrency pin으로만 변환한다.
        p_expected_submission_digest: correction.revision,
      },
    );
    if (error) return mapAuditRpcError(error);
    if (firstStatus(data) !== 'corrected') return auditUnavailable();
    return auditJson({ status: 'corrected' });
  } catch {
    return auditUnavailable();
  }
}
