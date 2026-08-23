import { NextRequest } from 'next/server';

import {
  auditInvalid,
  auditJson,
  loadAuditDetail,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: { itemId: string } },
) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (Array.from(req.nextUrl.searchParams.keys()).length > 0) return auditInvalid();

  const result = await loadAuditDetail(access.userId, params.itemId);
  if (!result.ok) return withAuditNoStore(result.response);
  return auditJson(result.item);
}
