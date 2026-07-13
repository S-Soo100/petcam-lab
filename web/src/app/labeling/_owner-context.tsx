'use client';

// 라벨링 접근 상태(owner/labeler/pending/rejected/unregistered)를 children 에 내려주는 컨텍스트.
//
// 왜 별도 모듈?
// - layout.tsx 에 createContext 를 박으면 컴포넌트 export 와 섞여 fast-refresh 가 깨진다.
// - hook 만 다른 페이지에서 단독 import 할 수 있다.
//
// 사용:
// - layout.tsx 가 <LabelingAccessProvider value={{ access, refresh }}>{children}</...>
// - children 에서 const { access } = useLabelingAccess();  또는  const isOwner = useIsOwner();
//
// useIsOwner 는 기존 호출부(단건 상세의 삭제 버튼 등) 호환을 위해 유지 —
// 이제 access.status === 'owner' 로 파생한다(과거의 /api/poc/summary 재사용 폐기, §8).

import { createContext, useContext } from 'react';

import type { LabelingAccessInfo } from '@/lib/labelingApi';

interface AccessContextValue {
  access: LabelingAccessInfo | null;
  refresh: () => void;
}

const AccessCtx = createContext<AccessContextValue>({
  access: null,
  refresh: () => {},
});

export function LabelingAccessProvider({
  value,
  children,
}: {
  value: AccessContextValue;
  children: React.ReactNode;
}) {
  return <AccessCtx.Provider value={value}>{children}</AccessCtx.Provider>;
}

export function useLabelingAccess(): AccessContextValue {
  return useContext(AccessCtx);
}

export function useIsOwner(): boolean {
  return useContext(AccessCtx).access?.status === 'owner';
}
