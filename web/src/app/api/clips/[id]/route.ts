import { NextRequest, NextResponse } from 'next/server';
import { revalidatePath } from 'next/cache';
import { supabaseAdmin } from '@/lib/supabase';
import { deleteObject } from '@/lib/r2';
import { loadClipWithPerms } from '@/lib/clipPerms';

// DELETE /api/clips/[id]
// 클립 영구 삭제 — owner-only.
//
// 삭제 순서 — DB 먼저, R2 나중 (원자성):
//  1. camera_clips 단일 DELETE (원자적). camera_clips 를 참조하는 child FK 는
//     labeling_tutorial_lessons(RESTRICT)만 빼고 전부 CASCADE 라, 이 한 번의 DELETE 가
//     behavior_labels/behavior_logs/clip_labeling_sessions/clip_labeling_session_revisions/
//     clip_router_*/router_review_* 를 같은 트랜잭션에 정리한다.
//  2. DB 삭제가 성공한 뒤에만 R2 mp4 + thumbnail 을 best-effort 로 삭제.
//
// 왜 DB 먼저? (부분 삭제 방지)
// - 예전엔 R2·라벨을 먼저 지우고 camera_clips 를 마지막에 지웠다. tutorial lesson RESTRICT 나
//   revision append-only 트리거가 마지막 삭제를 막으면 API 는 실패하는데 영상·라벨은 이미
//   사라지는 "부분 삭제" 가 났다.
// - 삭제가 제약으로 거부되는 두 경우는 전체가 롤백돼 아무것도 안 지워진다 → 409:
//     · tutorial lesson 이 이 clip 을 참조 → FK RESTRICT (23503)
//     · revision 이 있음 → CASCADE 가 revision 삭제를 시도하나 append-only 트리거가 막음 (0A000)
//   (DB 롤백 probe 로 실측: 0A000 차단 + behavior_labels 무변).
// - R2 만 남는 orphan 은 lifecycle/수동 청소로 회수 가능(추적 가능한 방향의 불일치).
//
// 권한 모델:
// - service_role 라우트라 토큰 검증을 직접 함 (RLS 우회 클라이언트라).
// - Bearer token → Supabase Auth getUser → user.id === DEV_USER_ID 매치.
// - /api/poc/summary 와 동일 패턴.

export const runtime = 'nodejs';

// GET /api/clips/[id]
// 클립 메타 단건 조회 — 라벨링 승인 사용자 전용.
export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const clipId = params.id;
  if (!clipId) {
    return NextResponse.json({ detail: 'clip id missing' }, { status: 400 });
  }
  const result = await loadClipWithPerms(req, clipId);
  if (!result.ok) return result.response;
  return NextResponse.json(result.access.clip);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const auth = req.headers.get('authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const {
    data: { user },
    error: authErr,
  } = await supabaseAdmin.auth.getUser(token);
  if (authErr || !user) {
    return NextResponse.json({ error: 'invalid token' }, { status: 401 });
  }

  const devUserId = process.env.DEV_USER_ID;
  if (!devUserId) {
    return NextResponse.json({ error: 'DEV_USER_ID 누락' }, { status: 500 });
  }
  if (user.id !== devUserId) {
    return NextResponse.json({ error: 'forbidden — owner only' }, { status: 403 });
  }

  const clipId = params.id;
  if (!clipId) {
    return NextResponse.json({ error: 'clip id 누락' }, { status: 400 });
  }

  // 1) clip 조회 (r2_key + thumbnail_r2_key 가 있으면 R2 도 청소)
  const { data: clip, error: selErr } = await supabaseAdmin
    .from('camera_clips')
    .select('id, user_id, r2_key, thumbnail_r2_key')
    .eq('id', clipId)
    .single();
  if (selErr || !clip) {
    return NextResponse.json({ error: 'clip not found' }, { status: 404 });
  }
  // 본인 소유 clip 만 — 미러 등 우회 방지.
  if (clip.user_id !== devUserId) {
    return NextResponse.json({ error: 'forbidden — not your clip' }, { status: 403 });
  }

  // 2) DB 삭제 먼저 — camera_clips 단일 원자 DELETE. child CASCADE 가 라벨/세션/라우터 정리.
  //    거부되면 전체 롤백(아무것도 안 지워짐) → 409. R2 는 이 뒤에만 건드린다.
  const { error: delErr } = await supabaseAdmin
    .from('camera_clips')
    .delete()
    .eq('id', clipId);
  if (delErr) {
    // FK RESTRICT(튜토리얼 기준 영상) → 삭제 불가.
    if (delErr.code === '23503') {
      return NextResponse.json(
        {
          error:
            '이 영상은 튜토리얼 기준 영상으로 사용 중이라 삭제할 수 없어. 튜토리얼에서 제외한 뒤 다시 시도해.',
        },
        { status: 409 },
      );
    }
    // append-only 트리거(보정 감사 기록 존재) → 삭제 불가.
    if (delErr.code === '0A000') {
      return NextResponse.json(
        {
          error:
            '이 영상엔 보정 감사 기록이 남아 있어 삭제할 수 없어(감사 기록은 영구 보존). 관리자에게 문의해.',
        },
        { status: 409 },
      );
    }
    // 그 외 DB 오류 — 내부 메시지는 로그로만, 응답은 일반 메시지.
    console.error('[clips DELETE] camera_clips delete failed', delErr);
    return NextResponse.json(
      { error: '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.' },
      { status: 500 },
    );
  }

  // 3) DB 삭제 성공 후에만 R2 best-effort 청소. 여기 도달 = clip + 모든 CASCADE child 원자 삭제됨.
  //    R2 실패는 추적 가능한 orphan 만 남기므로 요청을 실패시키지 않는다.
  const r2Errors: string[] = [];
  if (clip.r2_key) {
    try {
      await deleteObject(clip.r2_key);
    } catch (e) {
      r2Errors.push(`mp4(${clip.r2_key}): ${(e as Error).message}`);
    }
  }
  if (clip.thumbnail_r2_key) {
    try {
      await deleteObject(clip.thumbnail_r2_key);
    } catch (e) {
      r2Errors.push(`thumb(${clip.thumbnail_r2_key}): ${(e as Error).message}`);
    }
  }

  revalidatePath('/');
  revalidatePath('/queue');
  revalidatePath('/labeling');
  revalidatePath('/results');

  return NextResponse.json(
    {
      ok: true,
      clip_id: clipId,
      r2_errors: r2Errors.length > 0 ? r2Errors : undefined,
    },
    { status: 200 },
  );
}
