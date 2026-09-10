import { NextRequest, NextResponse } from 'next/server';

import { requireLabelingAccess } from '@/lib/labelingAccess';
import { isUuid } from '@/lib/uuid';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// POST /api/labeling-v4/media-error { clip_id, attempt, outcome: 'retrying'|'recovered'|'exhausted'|'manual_retry' }
// 영상 로드 실패 빈도를 알기 위한 서버 로그 한 줄(Vercel 로그에서 `[media-error]` 로 검색). DB write 없음.
// 일주일치 로그로 "R2 일시 장애인가, 특정 시간대인가"를 판단한다(2026-09-09 준비 계획 Task 6).
const OUTCOMES = new Set(['retrying', 'recovered', 'exhausted', 'manual_retry']);

export async function POST(req: NextRequest) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;
  let body: { clip_id?: unknown; attempt?: unknown; outcome?: unknown };
  try { body = await req.json(); } catch { return NextResponse.json({ ok: false }, { status: 400 }); }
  if (typeof body.clip_id !== 'string' || !isUuid(body.clip_id) || typeof body.outcome !== 'string' || !OUTCOMES.has(body.outcome)) {
    return NextResponse.json({ ok: false }, { status: 400 });
  }
  const attempt = Number.isInteger(body.attempt) ? (body.attempt as number) : 0;
  console.warn('[media-error]', JSON.stringify({ clip_id: body.clip_id, attempt, outcome: body.outcome, user: access.userId.slice(0, 8), at: new Date().toISOString() }));
  return NextResponse.json({ ok: true });
}
