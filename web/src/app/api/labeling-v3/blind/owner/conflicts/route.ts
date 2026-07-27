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
import { loadOwnerConflictScope } from '../../_access';

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
    const scoped = await loadOwnerConflictScope(
      req.nextUrl.searchParams.get('cohort_id'),
    );
    if (!scoped.ok) return scoped.response;

    // 기존 live 계약/RPC는 그대로 둔다. Canary만 정확한 cohort_id로 직접 조회해
    // 아직 generalized RPC가 없는 production DB에서도 교차-cohort 없이 검수한다.
    if (scoped.scope.cohortKind === 'canary') {
      let query = supabaseAdmin
        .from('motion_clip_consensus')
        .select('clip_id, differing_fields, updated_at')
        .eq('cohort_kind', 'canary')
        .eq('cohort_id', scoped.scope.cohortId)
        .eq('status', 'conflict');
      if (cursor) {
        query = query.or(
          `updated_at.lt.${cursor.updatedAt},and(updated_at.eq.${cursor.updatedAt},clip_id.lt.${cursor.clipId})`,
        );
      }
      const { data: consensusData, error: consensusError } = await query
        .order('updated_at', { ascending: false })
        .order('clip_id', { ascending: false })
        .limit(limit + 1);
      if (consensusError) throw consensusError;

      const rows = (consensusData ?? []) as {
        clip_id: string;
        differing_fields: string[] | null;
        updated_at: string;
      }[];
      const hasMore = rows.length > limit;
      const page = hasMore ? rows.slice(0, limit) : rows;
      const clipIds = page.map((row) => row.clip_id);
      const clipById = new Map<
        string,
        { started_at: string; camera_name: string | null }
      >();
      if (clipIds.length > 0) {
        const { data: clipData, error: clipError } = await supabaseAdmin
          .from('motion_clips')
          .select('id, started_at, cameras(name)')
          .in('id', clipIds);
        if (clipError) throw clipError;
        for (const raw of (clipData ?? []) as {
          id: string;
          started_at: string;
          cameras:
            | { name?: string | null }
            | { name?: string | null }[]
            | null;
        }[]) {
          const camera = Array.isArray(raw.cameras)
            ? raw.cameras[0]
            : raw.cameras;
          clipById.set(raw.id, {
            started_at: raw.started_at,
            camera_name: camera?.name ?? null,
          });
        }
      }
      const mappedRows: OwnerConflictRow[] = page.map((row) => {
        const clip = clipById.get(row.clip_id);
        if (!clip) throw new Error('missing clip metadata');
        return {
          ...row,
          started_at: clip.started_at,
          camera_name: clip.camera_name,
        };
      });
      const items = mappedRows.map(mapOwnerConflictRow);
      const last = page[page.length - 1];
      const nextCursor =
        hasMore && last ? encodeCursor(last.updated_at, last.clip_id) : null;
      return NextResponse.json({
        items,
        next_cursor: nextCursor,
        has_more: hasMore,
      });
    }

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
