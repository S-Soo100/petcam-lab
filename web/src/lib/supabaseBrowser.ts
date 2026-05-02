'use client';

// Supabase 브라우저 클라이언트 (anon key + Auth).
//
// `supabase.ts` 는 service_role 서버 전용. 이 파일은 클라이언트 컴포넌트에서 import 해서
// 로그인·세션 관리에만 사용. RLS 가 필터링을 책임지므로 anon key 노출은 정상 (Supabase
// 공식 가이드).
//
// 영상/라벨 데이터는 이 클라이언트로 직접 읽지 않고, 백엔드 FastAPI 가
// service_role 로 처리 (권한 매트릭스 일원화 — spec §4 결정 4).
// 이 클라이언트의 역할: 로그인 → JWT 보관 → 백엔드 API 호출 시 Authorization 헤더로 전달.
//
// `persistSession: true` 는 기본값. localStorage 에 토큰 저장 → 새로고침/탭 닫아도 유지.

import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let _client: SupabaseClient | null = null;

export function getSupabaseBrowser(): SupabaseClient {
  if (_client) return _client;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      'NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY 누락. web/.env.local 확인.',
    );
  }

  _client = createClient(url, anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: false,
    },
  });
  return _client;
}
