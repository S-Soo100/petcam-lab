// vitest 에서 `server-only` import 를 무력화하기 위한 스텁.
// 실제 패키지는 클라이언트/기본 조건에서 throw 하므로, 테스트(node 환경)에서
// 서버 모듈을 import 하면 로드 자체가 실패한다. vitest.config.ts 가 이 파일로 alias 한다.
export {};
