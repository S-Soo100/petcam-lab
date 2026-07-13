'use client';

// 팀원 관리 — owner 전용(§4.5).
//
// 구역: 승인 대기 / 활동 중 / 거절됨. 각 행에서 승인·거절·권한 해제·다시 승인.
// 작업 중 버튼은 비활성화하고 성공하면 목록을 다시 불러온다. owner 본인은 신청 row 가
// 없어 목록에 나타나지 않으므로 자기 권한 해제는 애초에 불가능하다(서버도 재차 거부).
//
// 레이아웃이 owner 에게만 이 경로를 허용하고, GET /api/labeling-team 도 서버에서 owner 를
// 다시 검증한다(이중 방어).

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import {
  ApiError,
  UnauthorizedError,
  decideLabelingTeam,
  getLabelingTeam,
  type LabelerApplication,
  type TeamDecision,
} from '@/lib/labelingApi';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';

function formatKst(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour12: false,
  });
}

export default function TeamPage() {
  const router = useRouter();
  const [apps, setApps] = useState<LabelerApplication[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const resp = await getLabelingTeam();
      setApps(resp.applications);
    } catch (cause) {
      if (cause instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setBusy(false);
    }
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  async function decide(userId: string, decision: TeamDecision) {
    setPendingId(userId);
    setErr(null);
    try {
      await decideLabelingTeam(userId, decision);
      await load();
    } catch (cause) {
      setErr(cause instanceof ApiError ? cause.message : (cause as Error).message);
    } finally {
      setPendingId(null);
    }
  }

  const waiting = apps.filter((a) => a.status === 'pending');
  const active = apps.filter((a) => a.status === 'approved');
  const rejected = apps.filter((a) => a.status === 'rejected');

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
            팀원 관리
          </h1>
          <p className="text-sm text-zinc-500">
            가입 신청을 승인·거절하고 활동 중 라벨러의 권한을 해제해.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={load} disabled={busy}>
          {busy ? '불러오는 중…' : '↻ 새로고침'}
        </Button>
      </div>

      {err && (
        <div className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          {err}
        </div>
      )}

      <Section
        title="승인 대기"
        tone="warning"
        rows={waiting}
        timeLabel="신청 시각"
        timeOf={(a) => a.requested_at}
        pendingId={pendingId}
        actions={(a) => [
          { label: '승인', onClick: () => decide(a.user_id, 'approve') },
          {
            label: '거절',
            variant: 'secondary',
            onClick: () => decide(a.user_id, 'reject'),
          },
        ]}
        empty="대기 중인 신청이 없어."
      />

      <Section
        title="활동 중"
        tone="success"
        rows={active}
        timeLabel="승인 시각"
        timeOf={(a) => a.reviewed_at}
        pendingId={pendingId}
        actions={(a) => [
          {
            label: '권한 해제',
            variant: 'danger',
            onClick: () => decide(a.user_id, 'deactivate'),
          },
        ]}
        empty="활동 중인 라벨러가 없어."
      />

      <Section
        title="거절됨"
        tone="danger"
        rows={rejected}
        timeLabel="처리 시각"
        timeOf={(a) => a.reviewed_at}
        pendingId={pendingId}
        actions={(a) => [
          { label: '다시 승인', onClick: () => decide(a.user_id, 'approve') },
        ]}
        empty="거절된 신청이 없어."
      />
    </main>
  );
}

interface RowAction {
  label: string;
  variant?: 'primary' | 'secondary' | 'danger';
  onClick: () => void;
}

function Section({
  title,
  tone,
  rows,
  timeLabel,
  timeOf,
  actions,
  pendingId,
  empty,
}: {
  title: string;
  tone: 'warning' | 'success' | 'danger';
  rows: LabelerApplication[];
  timeLabel: string;
  timeOf: (a: LabelerApplication) => string | null;
  actions: (a: LabelerApplication) => RowAction[];
  pendingId: string | null;
  empty: string;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        <CardTitle>{title}</CardTitle>
        <Badge tone={tone}>{rows.length}</Badge>
      </div>
      {rows.length === 0 ? (
        <Card padding="sm">
          <p className="text-sm text-zinc-500">{empty}</p>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((a) => (
            <Card key={a.user_id} padding="sm">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-zinc-800">
                    {a.display_name}
                  </div>
                  <div className="truncate text-xs text-zinc-500" title={a.email}>
                    {a.email}
                  </div>
                  <div className="mt-0.5 text-[11px] tabular-nums text-zinc-400">
                    {timeLabel}: {formatKst(timeOf(a))}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {actions(a).map((action) => (
                    <Button
                      key={action.label}
                      size="sm"
                      variant={action.variant ?? 'primary'}
                      onClick={action.onClick}
                      disabled={pendingId === a.user_id}
                    >
                      {pendingId === a.user_id ? '처리 중…' : action.label}
                    </Button>
                  ))}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}
