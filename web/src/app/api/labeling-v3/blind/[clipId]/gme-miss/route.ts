import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

// 구 탭이 별도 miss 원장에 계속 쓰면 통합 GME 오류 통계에서 조용히 빠진다.
// UI를 새로고침하면 신규 /gme-feedback endpoint로 안전하게 전환된다.
export async function POST() {
  return NextResponse.json({
    detail: 'GME 오류 기록 방식이 바뀌었어. 화면을 새로고침한 뒤 다시 눌러줘.',
    code: 'gme_feedback_endpoint_moved',
  }, { status: 410 });
}
