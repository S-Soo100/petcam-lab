import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ownerPreviewWorkerConfig } from '@/lib/yoloOwnerPreviewRoute';
import { OwnerYoloV25Preview } from './_owner-yolo-v25-preview';

export default function OwnerYoloV25PreviewPage() {
  if (!ownerPreviewWorkerConfig(process.env)) notFound();
  return (
    <main className="min-w-0 space-y-6 px-4 py-6">
      <header className="space-y-2">
        <Link className="text-sm font-medium text-emerald-700 hover:underline" href="/labeling/owner/yolo">
          ← 게코 bbox·모델 연구
        </Link>
        <h1 className="text-2xl font-semibold">YOLO v2.5 Owner Preview</h1>
        <p className="max-w-3xl text-sm text-zinc-600">
          사진이나 영상을 올려 격리된 development-only bbox 제안을 확인해.
          이 화면에는 저장·승인·학습 반영 경로가 없어.
        </p>
      </header>
      <OwnerYoloV25Preview />
    </main>
  );
}
