'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { BEHAVIOR_CLASSES, type BehaviorClass } from '@/types';
import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';

interface Props {
  clip: {
    id: string;
    started_at: string;
    duration_sec: number;
    source: string;
  };
  existing: { action: string; notes: string | null; created_at: string } | null;
}

export default function LabelForm({ clip, existing }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  // ?from=<path> — 어디서 들어왔는지. 저장 후 그쪽으로 복귀(예: /results?filter=mismatch)
  // open redirect 방지: 내부 path만 (`/`로 시작, `//`는 protocol-relative라 차단)
  const fromRaw = searchParams.get('from');
  const back = fromRaw && fromRaw.startsWith('/') && !fromRaw.startsWith('//') ? fromRaw : '/queue';
  const videoRef = useRef<HTMLVideoElement>(null);
  const [action, setAction] = useState<BehaviorClass | null>(
    existing && BEHAVIOR_CLASSES.includes(existing.action as BehaviorClass)
      ? (existing.action as BehaviorClass)
      : null,
  );
  const [notes, setNotes] = useState(existing?.notes ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(async () => {
    if (!action || saving) return;
    setSaving(true);
    setError(null);
    const res = await fetch('/api/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clip_id: clip.id, action, notes }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      setError(j.error ?? `저장 실패 (${res.status})`);
      setSaving(false);
      return;
    }
    router.refresh();
    router.push(back);
  }, [action, saving, clip.id, notes, router, back]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT')) return;

      const v = videoRef.current;
      if (!v) return;
      if (e.key === 'k' || e.key === ' ') {
        e.preventDefault();
        v.paused ? v.play() : v.pause();
      } else if (e.key === 'j') {
        v.currentTime = Math.max(0, v.currentTime - 1);
      } else if (e.key === 'l') {
        v.currentTime = Math.min(v.duration || Infinity, v.currentTime + 1);
      } else if (e.key >= '1' && e.key <= '9') {
        const idx = Number(e.key) - 1;
        const cls = BEHAVIOR_CLASSES[idx];
        if (cls) setAction(cls);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        void save();
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [save]);

  return (
    <main className="mx-auto max-w-5xl px-6 py-6 space-y-5">
      <div className="flex items-end justify-between gap-4">
        <div className="space-y-0.5">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
            라벨링{' '}
            <span className="font-mono text-sm font-normal text-zinc-400">
              {clip.id.slice(0, 8)}
            </span>
          </h1>
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <span>
              {new Date(clip.started_at).toLocaleString('ko-KR', {
                timeZone: 'Asia/Seoul',
                dateStyle: 'short',
                timeStyle: 'short',
              })}
            </span>
            <span className="text-zinc-300">·</span>
            <Badge tone={clip.source === 'upload' ? 'info' : 'neutral'}>{clip.source}</Badge>
            <span className="text-zinc-300">·</span>
            <span className="tabular-nums">{clip.duration_sec.toFixed(1)}s</span>
            {existing && (
              <>
                <span className="text-zinc-300">·</span>
                <Badge tone="warning">기존 라벨 → 덮어쓰기</Badge>
              </>
            )}
          </div>
        </div>
        <Link
          href={back}
          className="text-sm text-zinc-500 hover:text-zinc-900"
        >
          ← {back.startsWith('/results') ? '결과로' : '큐로'}
        </Link>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
        <div className="space-y-4">
          <video
            ref={videoRef}
            src={`/api/clips/${clip.id}/video`}
            controls
            autoPlay
            loop
            className="aspect-video w-full rounded-xl bg-black"
          />

          <div>
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
              행동 선택 (1~9)
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {BEHAVIOR_CLASSES.map((cls, i) => (
                <button
                  key={cls}
                  type="button"
                  onClick={() => setAction(cls)}
                  className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-all ${
                    action === cls
                      ? 'border-zinc-900 bg-zinc-900 text-white shadow-sm'
                      : 'border-zinc-200 bg-white text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50'
                  }`}
                >
                  <span
                    className={`grid h-5 w-5 place-items-center rounded text-[10px] font-semibold ${
                      action === cls ? 'bg-white/20 text-white' : 'bg-zinc-100 text-zinc-500'
                    }`}
                  >
                    {i + 1}
                  </span>
                  <span className="truncate">{cls}</span>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
              메모 (옵션)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="모호한 케이스의 판단 근거 등"
              rows={2}
              className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none"
            />
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button
              size="lg"
              variant="primary"
              onClick={save}
              disabled={!action || saving}
            >
              {saving ? '저장 중...' : action ? `저장 — ${action}` : '행동 선택 필요'}
            </Button>
            <span className="text-xs text-zinc-400">
              <kbd className="rounded border border-zinc-200 bg-white px-1 py-0.5 font-mono">Enter</kbd>{' '}
              로도 저장
            </span>
          </div>
        </div>

        <aside className="space-y-3">
          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <div className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500">
              단축키
            </div>
            <ul className="space-y-1.5 text-xs text-zinc-600">
              <ShortcutRow keys={['1', '~', '8']} desc="행동 라벨" />
              <ShortcutRow keys={['K', 'Space']} desc="재생 / 정지" />
              <ShortcutRow keys={['J', 'L']} desc="±1초 시킹" />
              <ShortcutRow keys={['Enter']} desc="저장" />
            </ul>
          </div>
          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 text-xs text-zinc-600">
            <div className="mb-1 font-medium text-zinc-700">우선순위 (멀티 행동)</div>
            <div className="leading-relaxed">
              eating_prey &gt; eating_paste &gt; drinking &gt; defecating &gt; basking &gt;
              moving &gt; hiding &gt; unseen
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}

function ShortcutRow({ keys, desc }: { keys: string[]; desc: string }) {
  return (
    <li className="flex items-center justify-between">
      <span className="flex items-center gap-1">
        {keys.map((k, i) => (
          <kbd
            key={i}
            className="rounded border border-zinc-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-zinc-700"
          >
            {k}
          </kbd>
        ))}
      </span>
      <span>{desc}</span>
    </li>
  );
}
