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
  { value: 'moving', label: '이동/움직임' },
  { value: 'static', label: '정지' },
  { value: 'feeding', label: '먹이/급여' },
  { value: 'drinking', label: '음수/핥기' },
  { value: 'hidden', label: '게코 숨음' },
  { value: 'unseen', label: '게코 안 보임' },
  { value: 'human_noise', label: '사람/그림자 노이즈' },
  { value: 'other', label: '기타' },
];
const OK_OPTIONS: { value: RouterReviewOk; label: string }[] = [
  { value: 'no', label: '검사' },
  { value: 'yes', label: '비검사' },
  { value: 'unclear', label: '애매함' },
];
const ROUTER_OK_HELP: { label: string; body: string }[] = [
  {
    label: '검사',
    body: 'VLM/사람이 봐야 하는 영상. 먹이, 음수/핥기, 이상 움직임, 중요한 상태 변화가 보이면 고른다.',
  },
  {
    label: '비검사',
    body: 'VLM/사람이 지금 안 봐도 되는 영상. 게코 안 보임, 사람/그림자 노이즈, 의미 없는 정지/움직임이면 고른다.',
  },
  {
    label: '애매함',
    body: '검사해야 할지 모르겠는 영상. 가림, 너무 작은 움직임, 다음 영상 필요, 노이즈와 행동 구분 불가일 때 고른다.',
  },
];

const ROUTE_COPY: Record<RouterReviewItem['route'], string> = {
  cloud_now: '지금 cloud VLM을 부를 후보',
  cloud_later: '급하지 않아 나중에 묶어서 볼 후보',
  activity_only: 'VLM 없이 활동량만 남길 후보',
  review_candidate: '자동 판단을 보류하고 리뷰할 후보',
};
const ROUTE_DETAIL: Record<RouterReviewItem['route'], string> = {
  cloud_now: '움직임/버스트가 강해서 바로 자세히 볼 가치가 있다고 본 결정.',
  cloud_later: '활동은 있지만 급한 신호는 낮아서 나중에 묶어서 봐도 된다고 본 결정.',
  activity_only: '중요 행동 가능성이 낮아 VLM 없이 활동량 기록만 남겨도 된다고 본 결정.',
  review_candidate: 'feature 신뢰도나 상황이 애매해서 자동 결정을 보류한 결정.',
};
const RISK_COPY: Record<RouterReviewItem['risk'], string> = {
  low: '낮음',
  medium: '중간',
  high: '높음',
};
const RISK_DETAIL: Record<RouterReviewItem['risk'], string> = {
  low: '라우터가 놓칠 위험이 낮다고 본 후보.',
  medium: '자동 확정 전 사람 확인이 필요한 후보.',
  high: '중요 움직임일 가능성이 있어 우선순위가 높은 후보.',
};
const RELIABILITY_COPY: Record<'low' | 'medium' | 'high', string> = {
  low: '낮음',
  medium: '중간',
  high: '높음',
};
const RELIABILITY_DETAIL: Record<'low' | 'medium' | 'high', string> = {
  low: 'OpenCV feature만으로 강한 결정을 내리기 어려운 영상.',
  medium: '기본 motion feature는 쓸 수 있지만 오판 가능성이 남은 영상.',
  high: 'motion feature가 비교적 안정적으로 계산된 영상.',
};
const REASON_COPY: Record<string, string> = {
  strong_activity_or_burst: '움직임/버스트가 강함',
  low_activity_batchable: '활동이 낮아 batch 처리 가능',
  moderate_activity_batchable: '중간 활동이라 batch 처리 가능',
  'feature_not_ready:missing_or_low_reliability': 'feature 부족 또는 낮은 신뢰도',
};

export default function RouterReviewClipPage() {
  const router = useRouter();
  const params = useParams<{ clipId: string }>();
  const searchParams = useSearchParams();
  const toast = useToast();
  const clipId = params.clipId;
  const batchId = searchParams.get('batch_id') || DEFAULT_BATCH_ID;
  const sampleGroup = searchParams.get('sample_group') || '';
  const status = (searchParams.get('status') || 'all') as
    | 'all'
    | 'reviewed'
    | 'unreviewed';

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
        getRouterReviewItem(clipId, batchId, {
          sample_group: sampleGroup || undefined,
          status,
        }),
        getClipFileUrl(clipId),
      ]);
      if (reviewResp.status === 'rejected') throw reviewResp.reason;
      const review = reviewResp.value;
      setItem(review.item);
      setNextClipId(review.next_clip_id ?? review.next_unreviewed_clip_id);
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
  }, [batchId, clipId, router, sampleGroup, status]);

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
      const nextParams = new URLSearchParams({ batch_id: batchId, status });
      if (sampleGroup) nextParams.set('sample_group', sampleGroup);
      if (nextClipId) {
        router.push(
          `/labeling/router-review/${nextClipId}?${nextParams.toString()}`,
        );
        return;
      }
      router.push(`/labeling/router-review?${nextParams.toString()}`);
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
          href={buildReviewListUrl(batchId, sampleGroup, status)}
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
              라우터가 이 영상을 VLM/사람 검수에 보낼 우선순위를 잘 정했는지 본다.
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
            hint="게코 자체가 안 보이면 unseen, 사람 손·그림자·세팅 변화가 원인이면 human_noise."
            options={ACTION_OPTIONS}
            value={action}
            onChange={setAction}
          />
          <ChoiceGroup
            title="검사 필요 여부"
            hint="이 영상을 VLM/사람이 봐야 하면 검사, 안 봐도 되면 비검사, 모르겠으면 애매함."
            options={OK_OPTIONS}
            value={routerOk}
            onChange={setRouterOk}
          />
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
            <div className="font-semibold">검사 필요 여부 기준</div>
            <ul className="mt-1 space-y-1">
              {ROUTER_OK_HELP.map((row) => (
                <li key={row.label}>
                  <span className="font-semibold">{row.label}</span>: {row.body}
                </li>
              ))}
            </ul>
          </div>

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
                    buildReviewClipUrl(nextClipId, batchId, sampleGroup, status),
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
          route: {item.route}
        </Badge>
        <Badge tone="neutral">risk: {RISK_COPY[item.risk]}</Badge>
        <Badge tone="neutral">
          reliability: {item.evidence_reliability ? RELIABILITY_COPY[item.evidence_reliability] : '없음'}
        </Badge>
        <span className="text-xs tabular-nums text-zinc-500">{startedAt}</span>
      </div>
      <div className="mt-3 space-y-2 text-xs leading-5 text-zinc-600">
        <p>
          <span className="font-semibold text-zinc-900">route</span>: {ROUTE_COPY[item.route]}.{' '}
          {ROUTE_DETAIL[item.route]}
        </p>
        <p>
          <span className="font-semibold text-zinc-900">reason</span>:{' '}
          {REASON_COPY[item.reason] ?? item.reason}
        </p>
        <p>
          <span className="font-semibold text-zinc-900">risk</span>: {RISK_COPY[item.risk]}.{' '}
          {RISK_DETAIL[item.risk]}
        </p>
        <p>
          <span className="font-semibold text-zinc-900">reliability</span>:{' '}
          {item.evidence_reliability
            ? `${RELIABILITY_COPY[item.evidence_reliability]}. ${RELIABILITY_DETAIL[item.evidence_reliability]}`
            : '계산 안 됨.'}
        </p>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <Metric
          label="motion_mean"
          value={fmt(item.motion_mean)}
          hint="전체 샘플 프레임의 평균 움직임. 낮을수록 조용한 영상."
        />
        <Metric
          label="motion_peak"
          value={fmt(item.motion_peak)}
          hint="가장 크게 움직인 순간의 움직임. 순간 그림자/손도 튈 수 있음."
        />
        <Metric
          label="active_ratio"
          value={fmt(item.active_motion_ratio)}
          hint="움직임이 있었다고 본 샘플 프레임 비율. 0.133이면 약 13%."
        />
        <Metric
          label="bursts"
          value={item.motion_burst_count ?? '-'}
          hint="움직임이 연속으로 묶인 덩어리 개수."
        />
      </dl>
    </Card>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint: string;
}) {
  return (
    <div>
      <dt className="text-zinc-500">{label}</dt>
      <dd className="mt-0.5 font-mono text-zinc-900">{value}</dd>
      <dd className="mt-1 leading-4 text-zinc-500">{hint}</dd>
    </div>
  );
}

function ChoiceGroup<T extends string>({
  title,
  hint,
  options,
  value,
  onChange,
}: {
  title: string;
  hint?: string;
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
}) {
  return (
    <div className="space-y-2">
      <div>
        <div className="text-sm font-medium text-zinc-700">{title}</div>
        {hint && <div className="mt-0.5 text-xs leading-5 text-zinc-500">{hint}</div>}
      </div>
      <div className="grid grid-cols-2 gap-2">
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

function buildReviewListUrl(
  batchId: string,
  sampleGroup: string,
  status: 'all' | 'reviewed' | 'unreviewed',
): string {
  const params = new URLSearchParams({ batch_id: batchId, status });
  if (sampleGroup) params.set('sample_group', sampleGroup);
  return `/labeling/router-review?${params.toString()}`;
}

function buildReviewClipUrl(
  clipId: string,
  batchId: string,
  sampleGroup: string,
  status: 'all' | 'reviewed' | 'unreviewed',
): string {
  const params = new URLSearchParams({ batch_id: batchId, status });
  if (sampleGroup) params.set('sample_group', sampleGroup);
  return `/labeling/router-review/${clipId}?${params.toString()}`;
}
