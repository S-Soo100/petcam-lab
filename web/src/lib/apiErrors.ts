import 'server-only';

import { NextResponse } from 'next/server';

const PUBLIC_DATABASE_ERROR =
  '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.';

export function databaseUnavailable(context: string, cause: unknown) {
  console.error(`[${context}] database unavailable`, cause);
  return NextResponse.json({ detail: PUBLIC_DATABASE_ERROR }, { status: 502 });
}
