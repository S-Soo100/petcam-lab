import { NextRequest } from 'next/server';

import {
  AUDIT_MEDIA_TTL_SEC,
  auditInvalid,
  auditJson,
  auditUnavailable,
  isValidAuditItemId,
  withAuditNoStore,
} from '@/lib/gmeNegativeAuditServer';
import { requireProductionLabelingAccess } from '@/lib/labelingAccess';
import { issueOwnerPlaybackToken } from '../../../_playback-token';

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

  let token: string;
  try {
    token = issueOwnerPlaybackToken(params.itemId, access.userId, AUDIT_MEDIA_TTL_SEC);
  } catch {
    const unavailable = auditUnavailable();
    unavailable.headers.set('Referrer-Policy', 'no-referrer');
    return unavailable;
  }
  const response = auditJson({
    url: `/api/labeling-v3/gme-audit/owner/${encodeURIComponent(params.itemId)}/file?token=${encodeURIComponent(token)}`,
    expires_in: AUDIT_MEDIA_TTL_SEC,
  });
  response.headers.set('Referrer-Policy', 'no-referrer');
  return response;
}
