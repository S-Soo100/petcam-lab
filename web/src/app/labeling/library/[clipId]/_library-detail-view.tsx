'use client';

import Link from 'next/link';

import Badge from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { labelSourceCopy, labelStateCopy, type LabelingLibraryItem } from '@/lib/labelingRoleData';
import { VideoPlayer } from '../../_labeling-forms';

// 순수 상세 뷰(SSR 테스트 대상). 읽기 전용 — 어떤 write control 도 렌더하지 않는다.
export function LibraryDetailView({
  item,
  videoUrl,
  backHref,
  getDownload,
}: {
  item: LabelingLibraryItem;
  videoUrl: string | null;
  backHref: string;
  getDownload: () => Promise<{ url: string; filename: string }>;
}) {
  const isFinal = item.label_state === 'final';
  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <div className="flex items-center justify-between gap-2">
        <Link href={backHref} className="text-sm text-emerald-600 hover:underline">
          ← 목록으로
        </Link>
        <Badge tone="neutral">읽기 전용</Badge>
      </div>

      <VideoPlayer src={videoUrl} getDownload={getDownload} />

      <Card className="space-y-2 text-sm">
        <div className="font-medium text-zinc-900">{item.camera_name ?? '카메라'}</div>
        <div className="text-xs text-zinc-500">
          {formatClipCapturedAt(item.started_at, item.duration_sec)}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={isFinal ? 'success' : 'info'}>{labelStateCopy(item.label_state)}</Badge>
          <Badge tone="neutral">{labelSourceCopy(item.label_source)}</Badge>
        </div>

        {isFinal ? (
          <div className="space-y-1">
            {item.final_decision && (
              <div className="text-sm text-zinc-800">최종 판정: {item.final_decision}</div>
            )}
            <FinalGtSummary gt={item.final_gt} />
          </div>
        ) : (
          <div className="text-sm text-zinc-600">{labelStateCopy(item.label_state)}</div>
        )}
      </Card>
    </main>
  );
}

// 최종 GT 요약 — final 일 때만 호출. 대표 행동/구간 수만 짧게. write 폼이 아니다(읽기 전용).
function FinalGtSummary({ gt }: { gt: unknown }) {
  if (!gt || typeof gt !== 'object') return null;
  const record = gt as Record<string, unknown>;
  const primary = record.primary_action ?? record.action;
  const segments = Array.isArray(record.segments) ? record.segments.length : null;
  const parts: string[] = [];
  if (typeof primary === 'string' && primary) parts.push(primary);
  if (segments != null) parts.push(`구간 ${segments}개`);
  if (parts.length === 0) return null;
  return <div className="text-xs text-zinc-600">기록: {parts.join(' · ')}</div>;
}
