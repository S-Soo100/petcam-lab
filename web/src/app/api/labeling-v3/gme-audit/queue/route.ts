import { NextRequest } from 'next/server';

import { mapAuditQueueRow } from '@/lib/gmeNegativeAudit';
import {
  auditInvalid,
  auditJson,
  auditUnavailable,
  mapAuditRpcError,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function progress(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN;
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
}

export async function GET(req: NextRequest) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (Array.from(req.nextUrl.searchParams.keys()).length > 0) return auditInvalid();

  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_gme_negative_audit_queue', {
      p_reviewer_id: access.userId,
    });
    if (error) return mapAuditRpcError(error);
    const rows = Array.isArray(data) ? data : [];
    const first = rows[0] as Record<string, unknown> | undefined;
    const completed = first ? progress(first.completed) : 0;
    const total = first ? progress(first.total) : 0;
    if (completed === null || total === null || completed > total) return auditUnavailable();
    for (const value of rows) {
      const row = value as Record<string, unknown>;
      if (progress(row.completed) !== completed || progress(row.total) !== total) {
        return auditUnavailable();
      }
    }
    return auditJson({ items: rows.map(mapAuditQueueRow), completed, total });
  } catch {
    return auditUnavailable();
  }
}
