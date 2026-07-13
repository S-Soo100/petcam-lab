import { NextRequest, NextResponse } from 'next/server';
import { revalidatePath } from 'next/cache';
import { supabaseAdmin } from '@/lib/supabase';
import { isBehaviorClass } from '@/types';
import { isOwnerId, verifyBearer } from '@/lib/clipPerms';

// 레거시 PoC 라벨 기록 endpoint. 원래 무인증이라 누구나 behavior_logs(source='human')에
// 가짜 GT 를 owner 명의로 주입할 수 있어 eval GT 를 오염시켰다(호출처 0, 참조 PoC 페이지도 폐기).
// owner 전용으로 잠근다. 신규 라벨링은 /api/labeling-v2 흐름을 사용한다.
export async function POST(req: NextRequest) {
  const auth = await verifyBearer(req);
  if (!auth.ok) return auth.response; // 401
  const { userId } = auth.auth;
  if (!isOwnerId(userId)) {
    // env 누락(isOwnerId=false) 도 여기서 403 — 내부 UUID 미노출.
    return NextResponse.json({ error: 'forbidden' }, { status: 403 });
  }

  const body = await req.json().catch(() => null);
  if (!body || typeof body.clip_id !== 'string' || typeof body.action !== 'string') {
    return NextResponse.json({ error: 'clip_id, action 필수' }, { status: 400 });
  }
  if (!isBehaviorClass(body.action)) {
    return NextResponse.json({ error: `잘못된 action: ${body.action}` }, { status: 400 });
  }

  const { error } = await supabaseAdmin.from('behavior_logs').insert({
    clip_id: body.clip_id,
    frame_idx: 0,
    action: body.action,
    source: 'human',
    verified: true,
    notes: typeof body.notes === 'string' && body.notes.trim() ? body.notes.trim() : null,
    created_by: userId,
  });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  revalidatePath('/');
  return NextResponse.json({ ok: true }, { status: 201 });
}
