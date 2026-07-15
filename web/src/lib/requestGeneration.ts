// 비동기 요청 세대(generation) guard — 늦게 도착한 이전 요청의 응답이 새 화면 상태를
// 덮어쓰지 못하게 막는 작은 헬퍼.
//
// 사용: 컴포넌트에서 useRef(createRequestGeneration()) 로 하나 들고,
//   요청 시작 시 const gen = g.next(); 로 세대를 확보한 뒤,
//   await 이후 setState 하기 전에 if (!g.isCurrent(gen)) return; 로 stale 을 버린다.
// clipId/필터가 바뀌어 새 요청이 시작되면 next() 가 세대를 올려 이전 응답을 무효화한다.

export interface RequestGeneration {
  // 새 요청 세대를 발급하고 현재 세대로 만든다.
  next(): number;
  // 현재 세대 번호.
  current(): number;
  // 주어진 세대가 아직 최신인지(그 사이 새 요청이 없었는지).
  isCurrent(gen: number): boolean;
}

export function createRequestGeneration(): RequestGeneration {
  let generation = 0;
  return {
    next: () => (generation += 1),
    current: () => generation,
    isCurrent: (gen: number) => gen === generation,
  };
}
