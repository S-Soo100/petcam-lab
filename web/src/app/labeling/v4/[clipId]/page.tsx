import V4ClipDetail from '../_v4-clip-detail';

// /labeling/v4/<clipId> — 하이라이트 확정 상세. 로직은 client 컴포넌트에 있고 여기선 params 만 넘긴다.
export default function V4ClipPage({ params }: { params: { clipId: string } }) {
  return <V4ClipDetail clipId={params.clipId} />;
}
