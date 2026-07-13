import 'server-only';

import { NextRequest, NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';

// 권한 헬퍼 — `/api/clips/[id]/*` 라우트 공통.
//
// backend/clip_perms.py 의 web 버전. 동일한 권한 매트릭스:
// - owner: clip.user_id == 본인 → 모든 라벨/추론 조회 가능.
// - labeler: `labelers` 테이블 멤버 → clip 영상/라벨 폼 접근 (단, 본인 라벨만).
// - 외부인: 둘 다 아님 → 404 (존재 leak 방지).
//
// /api/clips/[id] DELETE 와 /api/poc/summary 가 비슷한 토큰 검증을 직접 박고
// 있었음 — 4개 endpoint 더 추가되면서 헬퍼로 분리. 백엔드와 같은 룰을 한 곳에
// 모아둬야 향후 분기가 늘어도 한쪽만 고치면 됨.

export interface ClipRow {
  id: string;
  user_id: string;
  r2_key: string | null;
  thumbnail_r2_key: string | null;
  file_path: string | null;
  thumbnail_path: string | null;
  // 호출부마다 필요한 컬럼이 달라 SELECT * 로 가져온다 — 단건 lookup 이라
  // 컬럼 추리는 비용이 의미 없음. 나머지 필드는 호출부에서 cast.
  [key: string]: unknown;
}

export interface ClipAccess {
  userId: string;
  clip: ClipRow;
  isOwner: boolean;
}

export type ClipAccessResult =
  | { ok: true; access: ClipAccess }
  | { ok: false; response: NextResponse };

export interface AuthOk {
  userId: string;
}

export type AuthResult =
  | { ok: true; auth: AuthOk }
  | { ok: false; response: NextResponse };

// Bearer token → user.id. 토큰 없거나 invalid 면 401.
export async function verifyBearer(req: NextRequest): Promise<AuthResult> {
  const auth = req.headers.get('authorization') || '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : null;
  if (!token) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'unauthorized' }, { status: 401 }),
    };
  }
  const {
    data: { user },
    error,
  } = await supabaseAdmin.auth.getUser(token);
  if (error || !user) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'invalid token' }, { status: 401 }),
    };
  }
  return { ok: true, auth: { userId: user.id } };
}

export async function isLabeler(userId: string): Promise<boolean> {
  const { data, error } = await supabaseAdmin
    .from('labelers')
    .select('user_id')
    .eq('user_id', userId)
    .limit(1);
  if (error) {
    // 502 케이스는 호출부가 핸들링 — 여기선 보수적으로 false.
    // 권한 부여를 막는 방향이므로 안전 (외부인 false-positive 가 아님).
    return false;
  }
  return (data ?? []).length > 0;
}

// owner 판정 SOT — auth.user.id === DEV_USER_ID (spec §5). env 누락이면 false
// (아무도 owner 로 승격되지 않음 — 관리 API 는 requireOwner 에서 503 으로 분리 처리).
export function isOwnerId(userId: string): boolean {
  const devUserId = process.env.DEV_USER_ID;
  return Boolean(devUserId) && userId === devUserId;
}

// clip_id 로 row 조회 + owner OR labeler 검증.
// 외부인/미존재 둘 다 404 (existence leak 방지) — backend/clip_perms.py 와 동치.
export async function loadClipWithPerms(
  req: NextRequest,
  clipId: string,
): Promise<ClipAccessResult> {
  const authResult = await verifyBearer(req);
  if (!authResult.ok) return authResult;
  const { userId } = authResult.auth;

  if (!clipId) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'clip id missing' }, { status: 400 }),
    };
  }

  // 라벨링 접근 게이트 — DEV owner 또는 실제 labelers 멤버만 (§8).
  // clip 조회 전에 먼저 막아서 pending/rejected/unregistered 사용자가
  // 자기 소유 clip 을 통해 라벨링 API 를 우회하지 못하게 한다.
  if (!isOwnerId(userId) && !(await isLabeler(userId))) {
    // 미승인/외부인은 존재 leak 방지 위해 404 (403 대신).
    return {
      ok: false,
      response: NextResponse.json({ detail: 'not found' }, { status: 404 }),
    };
  }

  const { data: clips, error: selErr } = await supabaseAdmin
    .from('camera_clips')
    .select('*')
    .eq('id', clipId)
    .limit(1);

  if (selErr) {
    return {
      ok: false,
      response: NextResponse.json(
        { detail: `supabase error: ${selErr.message}` },
        { status: 502 },
      ),
    };
  }

  const clip = (clips ?? [])[0] as ClipRow | undefined;
  if (!clip) {
    return {
      ok: false,
      response: NextResponse.json({ detail: 'not found' }, { status: 404 }),
    };
  }

  // clip 소유 여부 — 라벨 가시성 판정용(owner 는 전체 라벨/추론, labeler 는 본인만).
  // 접근 자체는 위 게이트에서 이미 owner-or-labeler 로 확정됐다.
  const isOwner = clip.user_id === userId;
  return { ok: true, access: { userId, clip, isOwner } };
}
