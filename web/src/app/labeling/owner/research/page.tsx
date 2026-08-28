// /labeling/owner/research — 접힌 연구 도구 허브(설계 §7.1). 격리함·라우터 리뷰·튜토리얼·legacy 큐
// 같은 실험성/진단 화면을 일반 업무 흐름에서 분리해 여기로만 모은다. 상시 핵심 메뉴로 노출하지 않는다.

import Link from 'next/link';

const TOOLS: { href: string; title: string; desc: string }[] = [
  { href: '/research/rap/recordings', title: 'RAP C500G 녹화', desc: '야간 원본·R2 업로드·누락 확인' },
  { href: '/labeling/quarantine', title: '격리함', desc: '결정 충돌·보류 클립 검토' },
  { href: '/labeling/router-review', title: '라우터 리뷰', desc: 'evidence/router 판정 리뷰' },
  { href: '/labeling/legacy', title: 'legacy 큐', desc: '기존 체계 라벨링 큐(참조)' },
  { href: '/labeling/tutorial', title: '튜토리얼', desc: '라벨링 교육 과정 미리보기' },
];

export default function OwnerResearchPage() {
  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="min-w-0">
        <Link href="/labeling/owner" className="text-sm text-emerald-600 hover:underline">
          ← 운영 현황
        </Link>
        <h1 className="mt-1 whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">
          연구 도구
        </h1>
        <p className="text-sm text-zinc-500">일반 라벨링 흐름과 분리된 진단·실험 화면이야.</p>
      </div>

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {TOOLS.map((t) => (
          <li key={t.href} className="min-w-0">
            <Link
              href={t.href}
              className="block min-w-0 rounded-xl border border-zinc-200 bg-white p-3 shadow-sm hover:border-zinc-400"
            >
              <div className="font-medium text-zinc-900">{t.title}</div>
              <div className="mt-0.5 text-xs text-zinc-500">{t.desc}</div>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
