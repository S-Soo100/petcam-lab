import Link from 'next/link';

import { DetectorDemo } from './_detector-demo';

export default function DetectorPage() {
  return (
    <main className="min-h-screen bg-zinc-50 px-4 py-10 text-zinc-950 sm:px-6">
      <div className="mx-auto max-w-5xl space-y-8">
        <header className="space-y-3">
          <Link className="text-sm font-medium text-emerald-700 hover:underline" href="/">← petcam-lab</Link>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-emerald-700">Research demo</p>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">게코 찾기 연구실</h1>
          <p className="max-w-3xl text-zinc-600">
            사진이나 짧은 영상을 올리면 versioned bbox 결과를 보여줘. 지금 연결된 fake는 화면과 worker 계약을 검증하는 시연용이며 실제 YOLO checkpoint가 아니야.
          </p>
        </header>
        <DetectorDemo />
      </div>
    </main>
  );
}
