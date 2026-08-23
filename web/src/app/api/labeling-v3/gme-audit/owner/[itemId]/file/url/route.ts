import { NextRequest } from 'next/server';

import {
  AUDIT_MEDIA_TTL_SEC,
  auditInvalid,
  auditJson,
  isValidAuditItemId,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

function ownerRequired() {
  return auditJson({ detail: 'Owner만 접근할 수 있어.', code: 'owner_required' }, 403);
}

export async function GET(
  req: NextRequest,
  { params }: { params: { itemId: string } },
) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (!access.isOwner) return ownerRequired();
  if (!isValidAuditItemId(params.itemId) || Array.from(req.nextUrl.searchParams.keys()).length > 0) {
    return auditInvalid();
  }

  return auditJson({
    url: `/api/labeling-v3/gme-audit/owner/${encodeURIComponent(params.itemId)}/file`,
    expires_in: AUDIT_MEDIA_TTL_SEC,
  });
}
