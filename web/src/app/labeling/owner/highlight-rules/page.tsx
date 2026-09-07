'use client';

// owner 규칙 화면(v0 최소, 계획 Self-Review Step 5b). active 규칙 params 를 보고, 새 버전을 JSON 으로
// 저장·활성화하고, 최근 7일 유지율(규칙 × 카메라) 표를 본다. 숫자 검증은 서버/DB 가 최종.
// 경로 `/labeling/owner/**` 는 layout 가드가 이미 owner 전용으로 잠그고 API 도 requireOwner 로 재검증.

import { useCallback, useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { ApiError } from '@/lib/labelingApi';

interface ActiveRule {
  version: string;
  params: unknown;
  activated_at: string;
}

interface StatsRow {
  rule_version: string;
  camera_name: string | null;
  verdict_count: number;
  kept_ratio: number | null;
  o_to_x: number;
  x_to_o: number;
  reason_counts: Record<string, number>;
}

async function authed<T>(path: string, init?: RequestInit): Promise<T> {
  const { getSupabaseBrowser } = await import('@/lib/supabaseBrowser');
  const {
    data: { session },
  } = await getSupabaseBrowser().auth.getSession();
  const resp = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session?.access_token ?? ''}`,
      ...((init?.headers as Record<string, string>) ?? {}),
    },
  });
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, body?.detail ?? `HTTP ${resp.status}`, undefined, body?.code);
  return body as T;
}

export default function HighlightRulesPage() {
  const [active, setActive] = useState<ActiveRule | null>(null);
  const [stats, setStats] = useState<{ rows: StatsRow[] } | null>(null);
  const [version, setVersion] = useState('');
  const [params, setParams] = useState('');
  const [note, setNote] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const a = await authed<ActiveRule>('/api/labeling-v4/owner/highlight-rules');
      setActive(a);
      setParams(JSON.stringify(a.params, null, 2));
      setStats(await authed<{ rows: StatsRow[] }>('/api/labeling-v4/owner/highlight-stats'));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(params);
      } catch {
        throw new Error('params 가 JSON 이 아니야.');
      }
      await authed('/api/labeling-v4/owner/highlight-rules', {
        method: 'POST',
        body: JSON.stringify({ version, params: parsed, note }),
      });
      setVersion('');
      setNote('');
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-w-0 space-y-4 px-4 py-6">
      <h1 className="text-xl font-semibold text-zinc-900">하이라이트 규칙</h1>
      {err && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{err}</Card>}
      <Card className="space-y-2">
        <CardTitle>활성 규칙 {active?.version ?? '-'}</CardTitle>
        <p className="text-xs text-zinc-500">
          활성화{' '}
          {active?.activated_at
            ? new Date(active.activated_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })
            : '-'}
        </p>
        <input
          className="w-full rounded border px-2 py-1 text-sm"
          placeholder="hl-rule-v1"
          value={version}
          onChange={(e) => setVersion(e.target.value)}
        />
        <textarea
          className="h-56 w-full rounded border px-2 py-1 font-mono text-xs"
          value={params}
          onChange={(e) => setParams(e.target.value)}
        />
        <input
          className="w-full rounded border px-2 py-1 text-sm"
          placeholder="왜 바꿨나 한 줄"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button variant="labelingPrimary" disabled={busy || !version} onClick={save}>
          새 버전 저장 + 활성화
        </Button>
      </Card>
      <Card className="space-y-2">
        <CardTitle>최근 7일 유지율 (규칙 × 카메라)</CardTitle>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="text-left">규칙</th>
                <th className="text-left">카메라</th>
                <th>확정</th>
                <th>유지율</th>
                <th>O→X</th>
                <th>X→O</th>
                <th className="text-left">사유</th>
              </tr>
            </thead>
            <tbody>
              {(stats?.rows ?? []).map((r, i) => (
                <tr key={i}>
                  <td>{r.rule_version}</td>
                  <td>{r.camera_name ?? '-'}</td>
                  <td className="text-center">{r.verdict_count}</td>
                  <td className="text-center">{r.kept_ratio === null ? '-' : `${Math.round(r.kept_ratio * 100)}%`}</td>
                  <td className="text-center">{r.o_to_x}</td>
                  <td className="text-center">{r.x_to_o}</td>
                  <td>
                    {Object.entries(r.reason_counts)
                      .map(([k, v]) => `${k} ${v}`)
                      .join(', ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {stats && stats.rows.length === 0 && <p className="text-xs text-zinc-500">최근 7일 확정이 없어.</p>}
      </Card>
    </main>
  );
}
