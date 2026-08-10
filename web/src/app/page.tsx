import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen items-center bg-zinc-950 px-6 py-12 text-white">
      <div className="mx-auto w-full max-w-4xl space-y-8">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-400">petcam-lab</p>
        <div className="space-y-4">
          <h1 className="text-4xl font-bold tracking-tight sm:text-6xl">게코 관찰을 데이터로 바꾸는 연구실</h1>
          <p className="max-w-2xl text-lg text-zinc-300">공개 감지 시연과 초대 팀원 라벨링 공간을 분리해 운영해.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link className="rounded-lg bg-emerald-500 px-5 py-3 font-semibold text-zinc-950 hover:bg-emerald-400" href="/gecko-detector">공개 게코 찾기</Link>
          <Link className="rounded-lg border border-zinc-600 px-5 py-3 font-semibold hover:bg-zinc-900" href="/labeling">팀원 라벨링</Link>
        </div>
      </div>
    </main>
  );
}
