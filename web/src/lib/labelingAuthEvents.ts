// 라벨링 레이아웃의 Supabase 인증 이벤트 처리 결정(설계 §9.2).
//
// 문제(§9.1): layout 이 onAuthStateChange 를 이벤트 종류 구분 없이 처리해 accessChecked 를
// 매번 false 로 만들면, 토큰 자동 갱신(TOKEN_REFRESHED — 창 비활성/복귀 시 발생)에도 중립
// 화면으로 바뀌며 lesson 컴포넌트가 언마운트되고 저장 전 입력이 초기화된다.
//
// 이 순수 함수가 "이 이벤트에 접근 상태를 어떻게 할지"만 결정한다. React 상태 변경은 호출 측(layout).
//   keep    — 같은 user 의 단순 갱신. 기존 access·child 를 유지한다(언마운트 금지).
//   recheck — user 변경/권한 갱신. access 를 다시 확인한다.
//   discard — 로그아웃/세션 소멸. access 를 버리고 로그인으로 보낸다.

export type AuthTransition = 'keep' | 'recheck' | 'discard';

export function decideAuthTransition(
  event: string,
  prevUserId: string | null,
  nextUserId: string | null,
): AuthTransition {
  // 세션이 사라지면(로그아웃 포함) 무조건 폐기.
  if (event === 'SIGNED_OUT' || nextUserId === null) return 'discard';

  switch (event) {
    case 'TOKEN_REFRESHED':
      // 토큰 자동 갱신 — 같은 user 면 화면·접근 상태를 유지한다.
      return nextUserId === prevUserId ? 'keep' : 'recheck';
    case 'SIGNED_IN':
      // 같은 user 의 재-SIGNED_IN(탭 복귀 등)은 유지, user 가 바뀌면 재확인.
      return prevUserId !== null && nextUserId === prevUserId ? 'keep' : 'recheck';
    case 'INITIAL_SESSION':
      // 초기 세션 — 같은 user 면 getSession 경로가 이미 확인했으니 유지.
      return prevUserId === nextUserId ? 'keep' : 'recheck';
    case 'USER_UPDATED':
      // 권한/프로필 갱신 — 접근을 다시 확인한다.
      return 'recheck';
    default:
      // 알 수 없는 이벤트는 보수적으로 재확인.
      return 'recheck';
  }
}
