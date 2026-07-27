import { Card } from '@/components/ui/Card';
import type { OwnerSubmissionView } from '@/lib/motionBlindReviewApi';
import {
  OWNER_DIFFERING_TITLE,
  ownerDifferenceRows,
} from './_blind-review-view';

interface OwnerConflictComparisonProps {
  fields: readonly string[];
  submissionA: OwnerSubmissionView | null;
  submissionB: OwnerSubmissionView | null;
  durationSec: number;
}

export function OwnerConflictComparison({
  fields,
  submissionA,
  submissionB,
  durationSec,
}: OwnerConflictComparisonProps) {
  if (fields.length === 0) return null;
  const rows = ownerDifferenceRows(fields, submissionA, submissionB, durationSec);

  return (
    <Card className="border-amber-200 bg-amber-50/70">
      <div className="font-semibold text-amber-950">{OWNER_DIFFERING_TITLE}</div>
      <p className="mt-1 text-xs leading-relaxed text-amber-800">
        항목마다 두 라벨러가 실제로 고른 값을 비교해.
      </p>
      <div className="mt-3 space-y-2">
        {rows.map((row) => (
          <section key={row.key} className="rounded-xl border border-amber-200/80 bg-white p-3">
            <h3 className="text-sm font-semibold text-zinc-900">{row.label}</h3>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <div className="min-w-0 rounded-lg border border-sky-200 bg-sky-50 p-2.5">
                <div className="text-[11px] font-semibold text-sky-700">A 선택</div>
                <div className="mt-1 break-words text-sm font-medium leading-snug text-zinc-900">
                  {row.aValue}
                </div>
              </div>
              <div className="min-w-0 rounded-lg border border-violet-200 bg-violet-50 p-2.5">
                <div className="text-[11px] font-semibold text-violet-700">B 선택</div>
                <div className="mt-1 break-words text-sm font-medium leading-snug text-zinc-900">
                  {row.bValue}
                </div>
              </div>
            </div>
          </section>
        ))}
      </div>
    </Card>
  );
}

