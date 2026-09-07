import { NextRequest, NextResponse } from 'next/server';

import { HIGHLIGHT_TRIGGERS } from '@/lib/highlightV4';
import { highlightDatabaseError, highlightRpcErrorResponse } from '@/lib/highlightV4Server';
import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const VERSION_RE = /^hl-rule-v\d+$/;

function badRequest(detail: string) {
  return NextResponse.json({ detail, code: 'invalid_request' }, { status: 400 });
}

function validParams(v: unknown): v is { triggers: { name: string; on: boolean }[] } {
  if (!v || typeof v !== 'object') return false;
  const triggers = (v as { triggers?: unknown }).triggers;
  if (!Array.isArray(triggers) || triggers.length === 0) return false;
  return triggers.every((t) => t && typeof t === 'object'
    && (HIGHLIGHT_TRIGGERS as readonly string[]).includes((t as { name?: unknown }).name as string)
    && typeof (t as { on?: unknown }).on === 'boolean');
}

// GET — active 규칙(version·params·activated_at).
export async function GET(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_get_active_highlight_rule', {});
    if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    const row = (data ?? [])[0] as { version: string; params: unknown; activated_at: string } | undefined;
    if (!row) return NextResponse.json({ detail: '활성 규칙이 없어.', code: 'no_active_rule' }, { status: 503 });
    return NextResponse.json(row);
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}

// POST — body 에 params 가 있으면 새 버전 생성 + 즉시 활성화(숫자 검증은 DB eval 합성 실행이 최종),
// version 만 있으면 기존 버전 재활성화(잘못된 새 버전에서 검증된 버전으로 되돌리기). 둘 다 없으면 400.
export async function POST(req: NextRequest) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;
  let body: { version?: unknown; params?: unknown; note?: unknown };
  try { body = await req.json(); } catch { return badRequest('JSON 본문이 필요해.'); }
  if (typeof body.version !== 'string' || !VERSION_RE.test(body.version)) return badRequest('version 은 hl-rule-vN 형식이야.');
  if (body.params === undefined) {
    try {
      const { data, error } = await supabaseAdmin.rpc('fn_activate_highlight_rule_version', { p_version: body.version, p_actor_id: owner.userId });
      if (error) return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
      return NextResponse.json((data ?? [])[0] ?? null);
    } catch (cause) {
      return highlightDatabaseError(cause);
    }
  }
  if (!validParams(body.params)) return badRequest('params.triggers 가 잘못됐어(이름·on 필수).');
  const note = typeof body.note === 'string' ? body.note.slice(0, 500) : '';
  try {
    const { data, error } = await supabaseAdmin.rpc('fn_create_highlight_rule_version', {
      p_version: body.version, p_params: body.params, p_note: note, p_actor_id: owner.userId,
    });
    if (error) {
      if ((error as { code?: string }).code === '23505') return NextResponse.json({ detail: '이미 있는 버전이야.', code: 'conflict' }, { status: 409 });
      return highlightRpcErrorResponse(error) ?? highlightDatabaseError(error);
    }
    return NextResponse.json((data ?? [])[0] ?? null);
  } catch (cause) {
    return highlightDatabaseError(cause);
  }
}
