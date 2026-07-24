'use client';

// canary 동일 링크(설계 §8). 같은 URL 을 로그인 역할에 따라 다르게 렌더한다:
// - 라벨러: 자기에게 배정된 canary 작업 카드 + 본인 진행. 상대 답안·상대 상태 비공개.
// - Owner:  cohort 현황(전체/제출/상태 집계) + 두 라벨러 완료 수 + 공유 링크 복사 + 불일치 검수 진입.
// live 큐·활동일 progress 는 절대 건드리지 않는다. 닫힘/미존재 cohort 는 라벨러에게 만료로 접힌다.

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { getBlindCanary, type BlindCanaryResponse } from '@/lib/motionBlindReviewApi';

export default function BlindCanaryEntryPage() {
  const { cohortId } = useParams<{ cohortId: string }>();
  const [data, setData] = useState<BlindCanaryResponse | null>(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      setBusy(true);
      try {
        const res = await getBlindCanary(cohortId);
        if (alive) setData(res);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && (e.code === 'cohort_closed' || e.status === 410 || e.status === 404)) {
          setExpired(true);
        } else {
          setError(e instanceof ApiError ? e.message : (e as Error).message);
        }
      } finally {
        if (alive) setBusy(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [cohortId]);

  if (busy) return <main className="mx-auto max-w-3xl px-4 py-6 text-sm text-zinc-500">불러오는 중…</main>;

  if (expired) {
    return (
      <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
        <Card className="border-amber-200 bg-amber-50 text-sm text-amber-900">
          검증 링크가 만료됐어. 관리자에게 문의해.
        </Card>
        <Link className="text-sm text-emerald-700 underline" href="/labeling">홈으로 돌아가기</Link>
      </main>
    );
  }

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-6">
        <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>
      </main>
    );
  }

  if (!data) return null;
  return data.role === 'owner' ? (
    <CanaryOwnerView data={data} />
  ) : (
    <CanaryLabelerView data={data} cohortId={cohortId} />
  );
}

// 라벨러 뷰 — 자기 작업 카드. 상대 답안·상대 진행은 응답에 없다(설계 §8).
export function CanaryLabelerView({
  data,
  cohortId,
}: {
  data: Extract<BlindCanaryResponse, { role: 'labeler' }>;
  cohortId: string;
}) {
  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <div className="inline-flex w-fit rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-900">
        검증용 작업
      </div>
      <Card className="text-sm text-zinc-700">
        검증 진행 {data.submitted_count}/{data.total_count}
      </Card>

      {data.items.length === 0 ? (
        <Card className="text-sm text-zinc-700">검증 작업을 모두 끝냈어.</Card>
      ) : (
        <ul className="space-y-2">
          {data.items.map((item) => (
            <li key={item.id}>
              <Link
                href={`/labeling/blind/canary/${cohortId}/${item.id}`}
                className="block rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
              >
                <div className="font-medium text-zinc-900">{item.camera_name}</div>
                <div className="text-xs text-zinc-500">
                  {formatClipCapturedAt(item.started_at, item.duration_sec)}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

// Owner 뷰 — cohort 현황판. 두 라벨러 완료 수 + 상태 집계 + 공유 링크 + 불일치 검수 진입.
// 한 사람만 제출한 개별 답안은 표시하지 않는다(응답에 없음). 공유 링크 복사는 client 클립보드만.
export function CanaryOwnerView({
  data,
}: {
  data: Extract<BlindCanaryResponse, { role: 'owner' }>;
}) {
  const [copied, setCopied] = useState(false);
  const shareUrl =
    typeof window !== 'undefined' ? `${window.location.origin}${data.share_path}` : data.share_path;

  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="whitespace-nowrap text-xl font-semibold tracking-tight text-zinc-900">
            {data.label ?? '검증 코호트'}
          </h1>
          <Badge tone={data.status === 'open' ? 'success' : 'neutral'}>
            {data.status === 'open' ? '진행 중' : '종료'}
          </Badge>
        </div>
        <p className="text-sm text-zinc-500">전체 {data.clip_total}개 영상</p>
      </div>

      <Card className="space-y-2 text-sm">
        <div className="font-medium text-zinc-900">라벨러별 완료</div>
        <ul className="space-y-1">
          {data.reviewers.map((r, i) => (
            <li key={i} className="flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-zinc-800">{r.display_name}</span>
              <span className="tabular-nums text-zinc-600">
                {r.submitted_count}/{r.total_count} 완료
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="space-y-1 text-sm">
        <div className="font-medium text-zinc-900">상태 집계</div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-zinc-700">
          <span>비교 대기 {data.counts.awaiting}</span>
          <span>합의 {data.counts.agreed}</span>
          <span>불일치 {data.counts.conflict}</span>
          <span>Owner 해결 {data.counts.owner_resolved}</span>
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            void navigator.clipboard?.writeText(shareUrl).then(() => setCopied(true));
          }}
        >
          {copied ? '링크 복사됨' : '라벨러 링크 복사'}
        </Button>
        <Link
          href="/labeling/blind/conflicts"
          className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-100"
        >
          불일치 검수로
        </Link>
      </div>
    </main>
  );
}
