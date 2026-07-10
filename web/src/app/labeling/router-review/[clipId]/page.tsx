'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';

import Badge from '@/components/ui/Badge';
import Button from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { useToast } from '@/components/Toast';
import {
  ApiError,
  UnauthorizedError,
  type PlaybackUrl,
  type RouterReviewActionGt,
  type RouterReviewItem,
  type RouterReviewOk,
  type RouterReviewVisibleGecko,
  getClipFileUrl,
  getRouterReviewItem,
  saveRouterReviewLabel,
} from '@/lib/labelingApi';

const DEFAULT_BATCH_ID = 'router-eval-v1-20260710';
const VISIBLE_OPTIONS: { value: RouterReviewVisibleGecko; label: string }[] = [
  { value: 'yes', label: '보임' },
  { value: 'no', label: '안 보임' },
  { value: 'unclear', label: '애매함' },
];
const ACTION_OPTIONS: { value: RouterReviewActionGt; label: string }[] = [
  { value: 'moving', label: 'moving' },
  { value: 'static', label: 'static' },
  { value: 'feeding', label: 'feeding' },
  { value: 'drinking', label: 'drinking' },
  { value: 'hidden', label: 'hidden' },
  { value: 'human_noise', label: 'human_noise' },
  { value: 'other', label: 'other' },
];
const OK_OPTIONS: { value: RouterReviewOk; label: string }[] = [
  { value: 'yes', label: '괜찮음' },
  { value: 'no', label: '위험/틀림' },
  { value: 'unclear', label: '애매함' },
];

export default function RouterReviewClipPage() {
  const router = useRouter();
  const params = useParams<{ clipId: string }>();
  const searchParams = useSearchParams();
  const toast = useToast();
  const clipId = params.clipId;
  const batchId = searchParams.get('batch_id') || DEFAULT_BATCH_ID;

  const [item, setItem] = useState<RouterReviewItem | null>(null);
  const [nextClipId, setNextClipId] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [visible, setVisible] = useState<RouterReviewVisibleGecko | null>(null);
  const [action, setAction] = useState<RouterReviewActionGt | null>(null);
  const [routerOk, setRouterOk] = useState<RouterReviewOk | null>(null);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setErr(null);
    setVideoUrl(null);
    try {
      const [reviewResp, urlResp] = await Promise.allSettled([
        getRouterReviewItem(clipId, batchId),
        getClipFileUrl(clipId),
      ]);
      if (reviewResp.status === 'rejected') throw reviewResp.reason;
      const review = reviewResp.value;
      setItem(review.item);
      setNextClipId(review.next_unreviewed_clip_id);
      if (review.item.label) {
        setVisible(review.item.label.manual_visible_gecko);
        setAction(review.item.label.manual_action_gt);
        setRouterOk(review.item.label.manual_router_ok);
        setNotes(review.item.label.manual_notes ?? '');
      } else {
        setVisible(null);
        setAction(null);
        setRouterOk(null);
        setNotes('');
      }

      if (urlResp.status === 'fulfilled') {
        setVideoUrl((urlResp.value as PlaybackUrl).url);
      } else {
        const e = urlResp.reason;
        setErr(e instanceof ApiError ? e.message : (e as Error).message);
      }
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [batchId, clipId, router]);

  useEffect(() => {
    load();
  }, [load]);

  const canSave = useMemo(
    () => Boolean(visible && action && routerOk && !saving),
    [action, routerOk, saving, visible],
  );

  async function save() {
    if (!visible || !action || !routerOk) {
      setErr('세 가지 검수 값을 모두 골라줘.');
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await saveRouterReviewLabel(clipId, batchId, {
        manual_visible_gecko: visible,
        manual_action_gt: action,
        manual_router_ok: routerOk,
        manual_notes: notes.trim() || null,
      });
      toast.show('라우터 리뷰 저장됨', 'success');
      if (nextClipId) {
        router.push(
          `/labeling/router-review/${nextClipId}?batch_id=${encodeURIComponent(batchId)}`,
        );
        return;
      }
      router.push(`/labeling/router-review?batch_id=${encodeURIComponent(batchId)}`);
    } catch (e) {
      if (e instanceof UnauthorizedError) {
        router.replace('/labeling/login');
        return;
      }
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      setErr(msg);
      toast.show(`저장 실패: ${msg}`, 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-6 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <Link
          href={`/labeling/router-review?batch_id=${encodeURIComponent(batchId)}`}
          className="text-xs text-zinc-500 hover:text-zinc-800"
          prefetch={false}
        >
          ← 라우터 리뷰로
        </Link>
        {item?.label && <Badge tone="success">기존 리뷰 수정 중</Badge>}
      </div>

      <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-800 ring-1 ring-inset ring-amber-200">
        이 화면은 행동 GT 저장이 아니라 라우터 판단 검증용이야. 결과는
        router_review_labels에만 저장돼.
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.85fr)]">
        <div className="space-y-4">
          <Card padding="none" className="overflow-hidden">
            {videoUrl ? (
              <video
                key={videoUrl}
                src={videoUrl}
                controls
                playsInline
                className="block aspect-video w-full bg-black"
              />
            ) : (
              <div className="grid aspect-video w-full place-items-center bg-zinc-100 text-sm text-zinc-500">
                {busy ? '영상 로드 중…' : '영상 없음'}
              </div>
            )}
          </Card>

          {item && <RouterSnapshot item={item} />}
        </div>

        <Card className="space-y-5">
          <div>
            <CardTitle>검수 입력</CardTitle>
            <p className="mt-1 text-xs text-zinc-500">
              영상 기준으로 라우터 판단이 안전한지만 평가한다.
            </p>
          </div>

          <ChoiceGroup
            title="게코 보임"
            options={VISIBLE_OPTIONS}
            value={visible}
            onChange={setVisible}
          />
          <ChoiceGroup
            title="실제 행동"
            options={ACTION_OPTIONS}
            value={action}
            onChange={setAction}
          />
          <ChoiceGroup
            title="라우터 판단"
            options={OK_OPTIONS}
            value={routerOk}
            onChange={setRouterOk}
          />

          <label className="block space-y-1 text-sm font-medium text-zinc-700">
            <span>메모</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              className="block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 shadow-sm"
              placeholder="틀린 이유나 애매한 지점"
            />
          </label>

          {err && (
            <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-inset ring-red-200">
              {err}
            </div>
          )}

          <div className="flex gap-2">
            <Button onClick={save} disabled={!canSave} className="flex-1">
              {saving ? '저장 중…' : nextClipId ? '저장 후 다음' : '저장 후 목록'}
            </Button>
            {nextClipId && (
              <Button
                variant="secondary"
                onClick={() =>
                  router.push(
                    `/labeling/router-review/${nextClipId}?batch_id=${encodeURIComponent(batchId)}`,
                  )
                }
              >
                건너뛰기
              </Button>
            )}
          </div>
        </Card>
      </div>
    </main>
  );
}

function RouterSnapshot({ item }: { item: RouterReviewItem }) {
  const startedAt = item.started_at
    ? new Date(item.started_at).toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour12: false,
      })
    : '?';
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={item.route === 'cloud_now' ? 'danger' : item.route === 'cloud_later' ? 'info' : 'warning'}>
          {item.route}
        </Badge>
        <Badge tone="neutral">{item.risk}</Badge>
        <Badge tone="neutral">{item.evidence_reliability ?? 'no reliability'}</Badge>
        <span className="text-xs tabular-nums text-zinc-500">{startedAt}</span>
      </div>
      <div className="mt-3 text-sm font-medium text-zinc-900">{item.reason}</div>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Metric label="motion_mean" value={fmt(item.motion_mean)} />
        <Metric label="motion_peak" value={fmt(item.motion_peak)} />
        <Metric label="active_ratio" value={fmt(item.active_motion_ratio)} />
        <Metric label="bursts" value={item.motion_burst_count ?? '-'} />
      </dl>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="mt-0.5 font-mono text-zinc-900">{value}</dd>
    </div>
  );
}

function ChoiceGroup<T extends string>({
  title,
  options,
  value,
  onChange,
}: {
  title: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-zinc-700">{title}</div>
      <div className="grid grid-cols-3 gap-2">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`min-h-10 rounded-md border px-2 text-sm font-medium transition-colors ${
              value === option.value
                ? 'border-zinc-900 bg-zinc-900 text-white'
                : 'border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function fmt(value: number | null): string {
  return value === null ? '-' : value.toFixed(3);
}
