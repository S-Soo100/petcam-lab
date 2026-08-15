'use client';

import { useState } from 'react';
import Link from 'next/link';

import Button from '@/components/ui/Button';
import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import { mapYoloOwnerOverview, type YoloOwnerOverview } from '@/lib/yoloOwner';
import { BboxEditor } from '../../yolo/_bbox-editor';

async function bearerJson(path: string, body?: unknown): Promise<unknown> {
  const { data } = await getSupabaseBrowser().auth.getSession();
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      ...(data.session ? { Authorization: `Bearer ${data.session.access_token}` } : {}),
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String((payload as { detail: unknown }).detail) : 'Owner 요청을 완료하지 못했어.';
    throw new Error(detail);
  }
  return payload;
}

export function OwnerYoloView({ initial }: { initial: unknown }) {
  const [overview, setOverview] = useState<YoloOwnerOverview>(() => mapYoloOwnerOverview(initial));
  const [reason, setReason] = useState('사람 bbox와 원본을 직접 확인함');
  const [message, setMessage] = useState('Owner 승인 전 Dataset 미포함');
  const [datasetId, setDatasetId] = useState(() => mapYoloOwnerOverview(initial).datasets[0]?.id ?? '');
  const [inspected, setInspected] = useState<Set<string>>(() => new Set());

  async function refresh() {
    const next = mapYoloOwnerOverview(await bearerJson('/api/yolo-owner/reviews'));
    setOverview(next);
    setDatasetId((current) => next.datasets.some((dataset) => dataset.id === current)
      ? current
      : next.datasets[0]?.id ?? '');
  }

  async function decide(revisionId: string, decision: 'approve' | 'reject') {
    const dataset = datasetId || null;
    try {
      await bearerJson(`/api/yolo-owner/reviews/${revisionId}/decision`, {
        decision, reason, dataset_version_id: decision === 'approve' ? dataset : null,
      });
      setMessage(decision === 'approve' ? 'Owner 승인과 Dataset membership을 함께 기록했어.' : '반려를 기록했어.');
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : '판정을 기록하지 못했어.'); }
  }

  async function approveModel(version: string, decision: 'approve' | 'reject') {
    try {
      await bearerJson(`/api/yolo-owner/models/${version}/approval`, { decision, reason });
      setMessage(decision === 'approve' ? 'Owner 모델 승인 event를 기록했어.' : 'Owner 모델 반려 event를 기록했어.');
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : '모델 판정을 기록하지 못했어.'); }
  }

  async function freezeDataset() {
    if (!datasetId) return;
    try {
      await bearerJson(`/api/yolo-owner/datasets/${datasetId}/freeze`, { reason });
      setMessage('Dataset freeze event를 기록했어. 이 version에는 membership을 더 추가할 수 없어.');
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Dataset을 freeze하지 못했어.'); }
  }

  async function activate(version: string, action: 'activate' | 'rollback') {
    try {
      await bearerJson(`/api/yolo-owner/models/${version}/activate`, { action, reason });
      setMessage(action === 'rollback' ? '이전 version으로 rollback event를 기록했어.' : 'active model event를 기록했어.');
      await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : '모델 전환을 기록하지 못했어.'); }
  }

  return (
    <div className="space-y-8">
      <aside className="rounded-xl border border-violet-300 bg-violet-50 p-4 text-sm text-violet-950">
        <p className="font-semibold">YOLO v2.5 Development-only Owner Preview</p>
        <p className="mt-1">GT·Dataset·모델 activation과 격리된 bbox 제안 화면이야.</p>
        <Link className="mt-3 inline-block font-medium underline" href="/labeling/owner/yolo/preview">
          v2.5 bbox 제안 확인하기 →
        </Link>
      </aside>
      <p aria-live="polite" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-950">{message}</p>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">사람 bbox 승인 대기</h2>
        <div className="flex items-end gap-2"><label className="min-w-0 flex-1 text-sm"><span className="mb-1 block font-medium">승격할 Dataset version</span><select className="w-full rounded-lg border border-zinc-300 p-2" onChange={(event) => setDatasetId(event.target.value)} value={datasetId}>{overview.datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.version}</option>)}</select></label><Button disabled={!datasetId} onClick={freezeDataset} type="button" variant="secondary">Dataset freeze</Button></div>
        {overview.reviews.length === 0 ? <p className="text-sm text-zinc-500">대기 중인 revision이 없어.</p> : null}
        {overview.reviews.map((review) => (
          <article className="space-y-3 rounded-xl border border-zinc-200 p-4" key={review.revision_id}>
            <p className="text-sm">blind {review.blind_annotation.boxes.length}개 → revision {review.revision_annotation.boxes.length}개</p>
            <p className="text-sm text-zinc-600">{review.revision_reason} · prediction {review.prediction.model_version}</p>
            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-1"><p className="text-xs font-medium text-zinc-600">blind 사람 bbox</p><BboxEditor ariaLabel="blind bbox 검수 대상" boxes={review.blind_annotation.boxes} onChange={() => undefined} readOnly task={review.task} /></div>
              <div className="space-y-1"><p className="text-xs font-medium text-zinc-600">최종 사람 bbox(초록) · 모델 bbox(주황)</p><BboxEditor ariaLabel="bbox 검수 대상" boxes={review.revision_annotation.boxes} modelFrames={review.prediction.frames} onChange={() => undefined} readOnly task={review.task} /></div>
            </div>
            <label className="flex items-center gap-2 text-sm"><input checked={inspected.has(review.revision_id)} onChange={(event) => setInspected((current) => { const next = new Set(current); if (event.target.checked) next.add(review.revision_id); else next.delete(review.revision_id); return next; })} type="checkbox" />원본·blind·revision·model 박스를 직접 확인했어</label>
            <div className="flex gap-2"><Button disabled={!datasetId || !inspected.has(review.revision_id)} onClick={() => decide(review.revision_id, 'approve')}>Dataset 승인</Button><Button disabled={!inspected.has(review.revision_id)} onClick={() => decide(review.revision_id, 'reject')} variant="secondary">반려</Button></div>
          </article>
        ))}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Model activation gate</h2>
        <label className="block text-sm"><span className="mb-1 block font-medium">Owner 판정 사유</span><input className="w-full rounded-lg border border-zinc-300 p-2" onChange={(event) => setReason(event.target.value)} value={reason} /></label>
        {overview.models.map((model) => (
          <article className="space-y-2 rounded-xl border border-zinc-200 p-4 text-sm" key={model.version}>
            <div className="flex items-center justify-between"><strong>{model.version}</strong><span>{model.active ? 'ACTIVE' : 'inactive'}</span></div>
            <ul className="grid gap-1 sm:grid-cols-3"><li>고정 시험 {model.fixed_test_passed ? '통과' : '미통과'}</li><li>future holdout {model.future_holdout_passed ? '통과' : '미통과'}</li><li>Owner 모델 승인 {model.owner_approved ? '완료' : '미완료'}</li></ul>
            <div className="flex flex-wrap gap-2"><Button disabled={!model.fixed_test_passed || !model.future_holdout_passed} onClick={() => approveModel(model.version, 'approve')} variant="secondary">모델 승인 기록</Button><Button onClick={() => approveModel(model.version, 'reject')} variant="secondary">모델 반려</Button><Button disabled={!model.fixed_test_passed || !model.future_holdout_passed || !model.owner_approved} onClick={() => activate(model.version, 'activate')}>활성화</Button><Button disabled={!model.fixed_test_passed || !model.future_holdout_passed || !model.owner_approved} onClick={() => activate(model.version, 'rollback')} variant="secondary">이전 버전으로 롤백</Button></div>
          </article>
        ))}
      </section>
    </div>
  );
}
