import { NextRequest, NextResponse } from 'next/server';
import { Buffer } from 'node:buffer';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import {
  blindBadRequest,
  blindDatabaseError,
  blindRpcErrorResponse,
  mapOwnerConflictRow,
  type OwnerConflictRow,
} from '@/lib/motionBlindReviewServer';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// GET /api/labeling-v3/blind/owner/conflicts — live conflict keyset 목록(설계 §4.5). owner 전용.
// agreed/awaiting/resolved 는 제외한다. cursor 는 (updated_at, clip_id) opaque.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

function decodeCursor(raw: string | null): { updatedAt: string; clipId: string } | null | 'invalid' {
  if (!raw) return null;
  try {
    const v = JSON.parse(Buffer.from(raw, 'base64url').toString('utf8')) as Record<string, unknown>;
    if (v.v !== 1 || typeof v.t !== 'string' || !RFC3339.test(v.t) || typeof v.id !== 'string' || !UUID.test(v.id)) {
      return 'invalid';
    }
    return { updatedAt: v.t, clipId: (v.id as string).toLowerCase() };
  } catch {
    return 'invalid';
  }
}

function encodeCursor(updatedAt: string, clipId: string): string {
  return Buffer.from(JSON.stringify({ v: 1, t: updatedAt, id: clipId }), 'utf8').toString('base64url');
}

export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const cursor = decodeCursor(req.nextUrl.searchParams.get('cursor'));
  if (cursor === 'invalid') return blindBadRequest('페이지 위치가 올바르지 않아.');

  const limit = 30;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_list_motion_blind_conflicts', {
      p_cursor_updated_at: cursor?.updatedAt ?? null,
      p_cursor_clip_id: cursor?.clipId ?? null,
      p_limit: limit + 1,
    });
    if (error) return blindRpcErrorResponse(error) ?? blindDatabaseError(error);
    const rows = (data ?? []) as OwnerConflictRow[];
    const hasMore = rows.length > limit;
    const page = hasMore ? rows.slice(0, limit) : rows;
    const items = page.map(mapOwnerConflictRow);
    const last = page[page.length - 1];
    const nextCursor = hasMore && last ? encodeCursor(last.updated_at, last.clip_id) : null;
    return NextResponse.json({ items, next_cursor: nextCursor, has_more: hasMore });
  } catch (cause) {
    return blindDatabaseError(cause);
  }
}
