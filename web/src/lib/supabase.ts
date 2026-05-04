import 'server-only';
// Supabase Service Role 클라이언트. RLS 우회 권한이라 절대 client component에서 import 금지.
// `server-only` import는 클라이언트 번들에 들어가면 빌드 시 오류로 막아준다 (Next.js 13.4+ 표준 패턴).
import { createClient, type SupabaseClient } from '@supabase/supabase-js';

// Lazy 초기화 — module load 시점이 아니라 첫 access 시점에 env 검사 + createClient.
// Vercel build collect-page-data 단계에서 module load 만 일어나는데, 그때 env 누락이면
// 빌드 통째로 fail. PoC 라우트(/upload /queue /api/clips/...)는 prod 라벨링 도메인에서
// 호출 안 되니, build 통과 + runtime 호출 시점에만 throw 하면 충분.
//
// Proxy 패턴 채택 이유: `export const supabaseAdmin` 시그니처 유지 → 9개 importer 수정 불필요.
let _client: SupabaseClient | null = null;

function _getClient(): SupabaseClient {
  if (_client) return _client;

  const url = process.env.SUPABASE_URL;
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || !serviceRoleKey) {
    throw new Error('SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 누락. web/.env.local 확인.');
  }

  // Next.js 14+는 fetch()를 기본 캐시. supabase-js는 내부적으로 fetch를 쓰므로
  // `force-dynamic` 페이지에서도 SSR 결과가 stale될 수 있다 (dev 서버에서 특히 잦음).
  // `cache: 'no-store'`를 fetch 레벨에 박아서 항상 fresh 요청.
  _client = createClient(url, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
    global: {
      fetch: (input, init) => fetch(input, { ...init, cache: 'no-store' }),
    },
  });
  return _client;
}

export const supabaseAdmin = new Proxy({} as SupabaseClient, {
  get(_t, prop, receiver) {
    return Reflect.get(_getClient(), prop, receiver);
  },
});
