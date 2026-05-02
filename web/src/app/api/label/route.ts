import { NextRequest, NextResponse } from 'next/server';
import { revalidatePath } from 'next/cache';
import { supabaseAdmin } from '@/lib/supabase';
import { isBehaviorClass } from '@/types';

const DEV_USER_ID = process.env.DEV_USER_ID;
if (!DEV_USER_ID) throw new Error('DEV_USER_ID 누락');

export async function POST(req: NextRequest) {
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
    created_by: DEV_USER_ID,
  });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  revalidatePath('/');
  revalidatePath('/queue');
  revalidatePath('/inference');
  revalidatePath('/results');
  return NextResponse.json({ ok: true }, { status: 201 });
}
