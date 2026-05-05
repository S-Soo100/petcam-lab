'use client';

// labeling layout 의 isOwner state 를 children 에서 useIsOwner() 로 가져오는 컨텍스트.
//
// 왜 별도 모듈?
// - layout.tsx 에 createContext 박으면 같은 파일의 LabelingLayout 컴포넌트 export 와
//   섞여서 fast-refresh 가 잘 안 동작 (file 단위로 module identity 깨짐).
// - hook 단독 import 도 가능 (`useIsOwner` 만 다른 페이지에서 import).
//
// 사용:
// - layout.tsx 가 <OwnerProvider value={isOwner}>{children}</OwnerProvider>
// - children 에서 const isOwner = useIsOwner();

import { createContext, useContext } from 'react';

const OwnerCtx = createContext<boolean>(false);

export function OwnerProvider({
  value,
  children,
}: {
  value: boolean;
  children: React.ReactNode;
}) {
  return <OwnerCtx.Provider value={value}>{children}</OwnerCtx.Provider>;
}

export function useIsOwner(): boolean {
  return useContext(OwnerCtx);
}
