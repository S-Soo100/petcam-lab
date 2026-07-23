'use client';

import { Card } from '@/components/ui/Card';
import type { BlindWorkspace } from '@/lib/motionBlindReviewServer';
import {
  blindActivityDayHeader,
  blindLateAddedBadge,
  blindProgressLines,
} from './_blind-review-view';

// 그룹·담당 카메라·우선 활동일·진행률(설계 §4.1·§4.4). 집계 숫자만 — 멤버별 라벨/보류/제외 분포는
// 절대 표시하지 않는다(설계 §5.1). 이름은 display_name 우선(서버가 마스킹 이메일 fallback).
export default function BlindReviewProgress({ workspace }: { workspace: BlindWorkspace }) {
  const lines = blindProgressLines(workspace);
  const header = blindActivityDayHeader(workspace.priority_activity_day);
  const late = blindLateAddedBadge(workspace);

  return (
    <Card className="space-y-2">
      <div className="text-sm font-semibold text-zinc-900">
        {workspace.group_name ?? '내 그룹'}
      </div>
      {header && <div className="text-xs text-zinc-600">{header}</div>}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-800">
        <span>{lines.own}</span>
        <span>{lines.partner}</span>
      </div>
      <div className="text-xs text-zinc-600">{lines.group}</div>
      {late && (
        <div className="inline-flex w-fit rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-900">
          {late}
        </div>
      )}
    </Card>
  );
}
