import { NextRequest } from 'next/server';

import { validateAuditSubmission } from '@/lib/gmeNegativeAudit';
import {
  auditInvalid,
  auditJson,
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

  // shape/enum/finite-number errors are rejected before assignment lookup so malformed input
  // cannot change 400/404 ordering based on whether an item exists for this reviewer.
  try {
    validateAuditSubmission(body.value, Number.MAX_SAFE_INTEGER);
  } catch {
    return auditInvalid();
  }

  const assigned = await requireAuditAssignment(access.userId, params.itemId);
  if (!assigned.ok) return withAuditNoStore(assigned.response);

  let submission;
  try {
    submission = validateAuditSubmission(body.value, Number(assigned.row.duration_sec));
  } catch {
    return auditInvalid();
  }

  if (assigned.row.initial_verdict !== null) {
    return mapAuditRpcError({ code: 'PT410' });
  }

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_submit_gme_negative_audit', {
      p_item_id: params.itemId,
      p_reviewer_id: access.userId,
      p_verdict: submission.verdict,
      p_representative_sec: submission.representative_sec,
      p_bbox: submission.bbox,
    });
    if (error) return mapAuditRpcError(error);
    if (firstStatus(data) !== 'submitted') return auditUnavailable();
    return auditJson({ status: 'submitted' });
  } catch {
    return auditUnavailable();
  }
}
