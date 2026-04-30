import 'server-only';
// Supabase Service Role 클라이언트. RLS 우회 권한이라 절대 client component에서 import 금지.
// `server-only` import는 클라이언트 번들에 들어가면 빌드 시 오류로 막아준다 (Next.js 13.4+ 표준 패턴).
import { createClient } from '@supabase/supabase-js';

const url = process.env.SUPABASE_URL;
const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!url || !serviceRoleKey) {
  throw new Error('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 누락. web/.env.local 확인.');
}

// Next.js 14+는 fetch()를 기본 캐시. supabase-js는 내부적으로 fetch를 쓰므로
// `force-dynamic` 페이지에서도 SSR 결과가 stale될 수 있다 (dev 서버에서 특히 잦음).
// `cache: 'no-store'`를 fetch 레벨에 박아서 항상 fresh 요청.
export const supabaseAdmin = createClient(url, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
  global: {
    fetch: (input, init) => fetch(input, { ...init, cache: 'no-store' }),
  },
});
