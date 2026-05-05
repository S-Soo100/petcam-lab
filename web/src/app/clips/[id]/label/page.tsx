import { redirect } from 'next/navigation';

// 옛 라벨링 라우트 → 신 라우트 (`/labeling/[clipId]`) 로 영구 리다이렉트.
// 신 라우트는 R2 signed URL 로 영상 재생 — Vercel prod 에서 정상 동작.
// 옛 라우트의 video stream API (`/api/clips/[id]/video`) 는 로컬 fs.readFile 만 했었음 → 다음 cleanup 에서 제거.
export default function LegacyLabelRedirect({
  params,
  searchParams,
}: {
  params: { id: string };
  searchParams?: { from?: string };
}) {
  const sp = new URLSearchParams();
  if (searchParams?.from) sp.set('from', searchParams.from);
  const qs = sp.toString();
  redirect(`/labeling/${params.id}${qs ? `?${qs}` : ''}`);
}
