import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// `@/*` 경로 별칭을 tsconfig 와 맞추고, `server-only` 를 테스트에서 무력화한다.
// 이렇게 해야 서버 전용 모듈(clipPerms/labelingAccess 등)의 순수 로직을 vitest 로 검증할 수 있다.
//
// esbuild.jsx='automatic': tsconfig 는 Next.js 용으로 jsx=preserve 라 vite 가 .tsx 의 JSX 를
// 변환하지 않는다. 선택 컨트롤·쳇바퀴 입력의 표시 계약을 react-dom/server renderToStaticMarkup
// 으로 검증하려면 테스트 트랜스폼에서 JSX 를 automatic runtime 으로 변환해야 한다(테스트 전용,
// 앱 빌드는 tsconfig/Next 그대로). testing-library 의존은 추가하지 않는다.
export default defineConfig({
  oxc: { jsx: { runtime: 'automatic' } },
  resolve: {
    alias: {
      'server-only': fileURLToPath(
        new URL('./src/test/server-only-stub.ts', import.meta.url),
      ),
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
