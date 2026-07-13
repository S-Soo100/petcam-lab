import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// `@/*` 경로 별칭을 tsconfig 와 맞추고, `server-only` 를 테스트에서 무력화한다.
// 이렇게 해야 서버 전용 모듈(clipPerms/labelingAccess 등)의 순수 로직을 vitest 로 검증할 수 있다.
export default defineConfig({
  resolve: {
    alias: {
      'server-only': fileURLToPath(
        new URL('./src/test/server-only-stub.ts', import.meta.url),
      ),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
