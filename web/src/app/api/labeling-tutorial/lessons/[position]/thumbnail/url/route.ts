import { NextRequest, NextResponse } from 'next/server';

import { presignGet, SIGNED_URL_TTL_SEC } from '@/lib/r2';
import { requireLabelingAccess } from '@/lib/labelingAccess';
import { thumbnailKeyForClip } from '@/lib/labelingV2';
import { databaseUnavailable } from '@/lib/apiErrors';
import {
  loadActiveSetId,
  loadLessonByPosition,
  loadLessonClip,
  parsePosition,
} from '../../../../_helpers';

export const runtime = 'nodejs';

// GET /api/labeling-tutorial/lessons/[position]/thumbnail/url
// lesson clip 의 썸네일만 서명(설계 §12). 일반 clip UUID 우회 경로 없음.
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
    if (!clip) return NextResponse.json({ detail: 'not found' }, { status: 404 });

    let key: string;
    try {
      key = thumbnailKeyForClip(clip);
    } catch {
      return NextResponse.json({ detail: 'thumbnail unavailable' }, { status: 410 });
    }
    const url = await presignGet(key, SIGNED_URL_TTL_SEC);
    return NextResponse.json({ url, ttl_sec: SIGNED_URL_TTL_SEC, type: 'r2' });
  } catch (cause) {
    return databaseUnavailable('labeling tutorial thumbnail url', cause);
  }
}
