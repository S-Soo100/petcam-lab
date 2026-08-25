import { NextRequest } from 'next/server';

import {
  AUDIT_MEDIA_TTL_SEC,
  auditInvalid,
  auditJson,
  auditUnavailable,
  loadAuditMediaKey,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { presignGet } from '@/lib/r2';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  req: NextRequest,
  { params }: { params: { itemId: string } },
) {
  const access = await requireProductionLabelingAccess(req);
  if (!access.ok) return withAuditNoStore(access.response);
  if (Array.from(req.nextUrl.searchParams.keys()).length > 0) return auditInvalid();

  const media = await loadAuditMediaKey(access.userId, params.itemId);
  if (!media.ok) return withAuditNoStore(media.response);
  try {
    const url = await presignGet(media.r2Key, AUDIT_MEDIA_TTL_SEC);
    return auditJson({ url, expires_in: AUDIT_MEDIA_TTL_SEC });
  } catch {
    return auditUnavailable();
  }
}
