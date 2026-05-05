import { NextResponse } from 'next/server';

// 구 업로드 라우트 — fs.writeFile 로 로컬 디스크에 저장하던 흐름.
// Vercel serverless 는 stateless + ephemeral /tmp 라 prod 에선 동작 안 함.
// /api/upload/sign + /api/upload/finalize (R2 직접 PUT) 로 대체 — `/upload` 페이지가 새 흐름 사용.
//
// 이 파일은 다음 cleanup 에서 제거. 그 사이 외부에서 호출 들어올 수 있어 410 반환.

export async function POST() {
  return NextResponse.json(
    { error: '구 업로드 라우트. /api/upload/sign + /api/upload/finalize 로 대체됨.' },
    { status: 410 },
  );
}
