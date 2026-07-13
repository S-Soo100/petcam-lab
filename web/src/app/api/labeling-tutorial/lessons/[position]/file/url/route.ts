import { NextRequest, NextResponse } from 'next/server';

import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { databaseUnavailable } from '@/lib/apiErrors';
import {
  loadActiveSetId,
  loadLessonByPosition,
  loadLessonClip,
  parsePosition,
} from '../../../../_helpers';

export const runtime = 'nodejs';

// GET /api/labeling-tutorial/lessons/[position]/file/url
// 요청 lesson 의 clip 만 서명한다. 일반 clip UUID 입력 경로가 없어 우회 불가(설계 §12).
// 접근: owner 또는 labeler(owner preview). requireLabelingAccess 는 튜토리얼 완료를
// 강제하지 않으므로 학습 중인 labeler 도 lesson 영상을 볼 수 있다.
export async function GET(
  req: NextRequest,
  { params }: { params: { position: string } },
) {
  const access = await requireLabelingAccess(req);
  if (!access.ok) return access.response;

  const position = parsePosition(params.position);
  if (position === null) {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }

  try {
    const setId = await loadActiveSetId();
    if (!setId) return NextResponse.json({ detail: 'not found' }, { status: 404 });
    const lesson = await loadLessonByPosition(setId, position);
    if (!lesson) return NextResponse.json({ detail: 'not found' }, { status: 404 });
    const clip = await loadLessonClip(lesson.clip_id);
    if (!clip?.r2_key) {
      return NextResponse.json({ detail: 'clip has no R2 object' }, { status: 410 });
    }
    const url = await presignGet(clip.r2_key, SIGNED_URL_TTL_SEC);
    return NextResponse.json({ url, ttl_sec: SIGNED_URL_TTL_SEC, type: 'r2' });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial file url', cause);
  }
}
