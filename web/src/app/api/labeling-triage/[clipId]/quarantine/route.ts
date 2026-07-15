import { NextRequest, NextResponse } from 'next/server';

import { requireOwner } from '@/lib/labelingAccess';
import { supabaseAdmin } from '@/lib/supabase';
import { databaseUnavailable } from '@/lib/apiErrors';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// POST /api/labeling-triage/[clipId]/quarantine  body = { note? }
// owner-only(설계 §8.4). 본 큐에서 owner 가 직접 격리함으로 옮긴다.
// fn_manual_quarantine_clip_for_labeling 이 기존 owner_decision 을 초기화해 '검토 필요'로 이동.
// 이미 라벨링이 시작된 clip 은 거부한다.
export async function POST(
  req: NextRequest,
  { params }: { params: { clipId: string } },
) {
  const owner = await requireOwner(req);
  if (!owner.ok) return owner.response;

  const clipId = params.clipId;
  if (!UUID_RE.test(clipId)) {
    return NextResponse.json({ detail: '잘못된 clip id' }, { status: 400 });
  }

  // body 는 선택. 없거나 비어도 허용.
  let note: string | null = null;
  try {
    const raw = await req.text();
    if (raw.trim()) {
      const body = JSON.parse(raw) as { note?: unknown };
      if (body?.note !== undefined && body?.note !== null) {
        if (typeof body.note !== 'string' || body.note.length > 500) {
          return NextResponse.json({ detail: '메모가 너무 길어.' }, { status: 400 });
        }
        note = body.note;
      }
    }
  } catch {
    return NextResponse.json({ detail: '요청 형식이 잘못됐어.' }, { status: 400 });
  }

  const { data, error } = await supabaseAdmin.rpc('fn_manual_quarantine_clip_for_labeling', {
    p_clip_id: clipId,
    p_actor_id: owner.userId,
    p_note: note,
  });
  if (error) {
    if (error.code === '22023') {
      return NextResponse.json({ detail: '요청을 처리할 수 없어.' }, { status: 400 });
    }
    return databaseUnavailable('labeling triage manual quarantine', error);
  }

  const result = data as { ok?: boolean; code?: string; changed?: boolean } | null;
  if (!result || result.ok !== true) {
    const code = result?.code;
    if (code === 'not_found') {
      return NextResponse.json({ detail: '클립을 찾을 수 없어.' }, { status: 404 });
    }
    if (code === 'not_labelable') {
      return NextResponse.json(
        { detail: '아직 동기화되지 않아 격리할 수 없어.', code: 'not_labelable' },
        { status: 409 },
      );
    }
    if (code === 'labeling_started') {
      return NextResponse.json(
        { detail: '이미 라벨링이 시작되어 격리할 수 없어.', code: 'labeling_started' },
        { status: 409 },
      );
    }
    return NextResponse.json({ detail: '요청을 처리할 수 없어.' }, { status: 400 });
  }

  return NextResponse.json({ ok: true, changed: Boolean(result.changed) });
}
