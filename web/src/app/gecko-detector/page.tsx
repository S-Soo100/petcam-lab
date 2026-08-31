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
          <p className="w-fit rounded-full bg-emerald-100 px-3 py-1 text-sm font-semibold text-emerald-900">
            현재 분석 모델: YOLO v2.6
          </p>
          <p className="max-w-3xl text-zinc-600">
            사진이나 60초 이하 영상을 올리면 YOLO v2.6이 찾은 게코 박스를 보여줘. 연구용 결과라서 사람 확인이 필요해.
          </p>
        </header>
        <DetectorDemo />
      </div>
    </main>
  );
}
