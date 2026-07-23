'use client';

// owner 불일치 검수 목록(설계 §4.5). conflict 만 나온다(agreed 는 감사 화면). owner 전용 — layout
// 가드가 labeler 를 차단한다. agreed 감사는 별도(read-only)로 남겨둔다.

import { useEffect, useState } from 'react';
import Link from 'next/link';

import { Card, CardTitle } from '@/components/ui/Card';
import Button from '@/components/ui/Button';
import { ApiError } from '@/lib/labelingApi';
import { formatClipCapturedAt } from '@/lib/labelingV2';
import { getOwnerConflicts, type OwnerConflictItem } from '@/lib/motionBlindReviewApi';
import { OWNER_CONFLICT_TITLE, ownerDifferingFieldLabels } from '../../_blind-review-view';

export default function OwnerConflictListPage() {
  const [items, setItems] = useState<OwnerConflictItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(cur: string | null) {
    try {
      const res = await getOwnerConflicts(cur);
      setItems((prev) => (cur ? [...prev, ...res.items] : res.items));
      setCursor(res.next_cursor);
      setHasMore(res.has_more);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
      <CardTitle>{OWNER_CONFLICT_TITLE}</CardTitle>
      {busy && <p className="text-sm text-zinc-500">불러오는 중…</p>}
      {error && <Card className="border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</Card>}
      {!busy && items.length === 0 && (
        <Card className="text-sm text-zinc-700">지금 확인할 불일치 영상이 없어.</Card>
      )}
      <ul className="space-y-2">
        {items.map((item) => (
          <li key={item.id}>
            <Link
              href={`/labeling/blind/conflicts/${item.id}`}
              className="block rounded-xl border border-zinc-200 bg-white p-3 text-sm shadow-sm hover:border-zinc-400"
            >
              <div className="font-medium text-zinc-900">{item.camera_name}</div>
              <div className="text-xs text-zinc-500">{formatClipCapturedAt(item.started_at, null)}</div>
              {item.differing_fields.length > 0 && (
                <div className="mt-1 text-xs text-amber-800">
                  서로 다름: {ownerDifferingFieldLabels(item.differing_fields).join(', ')}
                </div>
              )}
            </Link>
          </li>
        ))}
      </ul>
      {!busy && hasMore && (
        <Button variant="labelingSecondary" size="md" className="w-full" onClick={() => load(cursor)}>
          더 불러오기
        </Button>
      )}
    </main>
  );
}
