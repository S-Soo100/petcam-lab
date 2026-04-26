'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { BEHAVIOR_CLASSES, type BehaviorClass } from '@/types';

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
  const videoRef = useRef<HTMLVideoElement>(null);
  const [action, setAction] = useState<BehaviorClass | null>(
    (existing && BEHAVIOR_CLASSES.includes(existing.action as BehaviorClass))
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
    router.push('/queue');
  }, [action, saving, clip.id, notes, router]);

  // 단축키 — textarea 포커스 시는 무시 (글자 입력 방해 방지)
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
      } else if (e.key >= '1' && e.key <= '8') {
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
    <main className="mx-auto max-w-3xl p-6 space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-bold">
          라벨링{' '}
          <span className="font-mono text-sm text-gray-500">{clip.id.slice(0, 8)}</span>
        </h1>
        <Link href="/queue" className="text-sm text-blue-600 hover:underline">
          ← 큐
        </Link>
      </div>
      <div className="text-sm text-gray-600">
        {new Date(clip.started_at).toLocaleString('ko-KR')} · {clip.source} ·{' '}
        {clip.duration_sec.toFixed(1)}s
        {existing && (
          <span className="ml-2 text-amber-600">기존 라벨 있음 → 덮어쓰기 됨</span>
        )}
      </div>

      <video
        ref={videoRef}
        src={`/api/clips/${clip.id}/video`}
        controls
        autoPlay
        loop
        className="w-full bg-black aspect-video"
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {BEHAVIOR_CLASSES.map((cls, i) => (
          <button
            key={cls}
            type="button"
            onClick={() => setAction(cls)}
            className={`border rounded p-2 text-sm text-left ${
              action === cls
                ? 'bg-blue-600 text-white border-blue-600'
                : 'hover:bg-gray-50'
            }`}
          >
            <span className="opacity-50 mr-2">{i + 1}</span>
            {cls}
          </button>
        ))}
      </div>

      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="메모 (옵션)"
        className="border rounded w-full p-2 text-sm"
        rows={2}
      />

      <div className="text-xs text-gray-500">
        <kbd className="border rounded px-1">1~8</kbd> 라벨 ·{' '}
        <kbd className="border rounded px-1">K</kbd>/<kbd className="border rounded px-1">Space</kbd> 재생/정지 ·{' '}
        <kbd className="border rounded px-1">J</kbd>/<kbd className="border rounded px-1">L</kbd> ±1초 ·{' '}
        <kbd className="border rounded px-1">Enter</kbd> 저장
      </div>

      {error && <div className="text-red-600 text-sm">{error}</div>}

      <button
        type="button"
        onClick={save}
        disabled={!action || saving}
        className="bg-blue-600 text-white rounded px-4 py-2 disabled:opacity-40"
      >
        {saving ? '저장 중...' : `저장 (${action ?? '라벨 선택'})`}
      </button>
    </main>
  );
}
