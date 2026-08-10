'use client';

import { useEffect, useState } from 'react';

import Button from '@/components/ui/Button';
import type { BlindWorkspace, HumanBox, RevealResult } from '@/lib/yoloContribution';
import { revealYoloPrediction, submitYoloBlind, submitYoloRevision } from '@/lib/yoloContributionApi';
import { BboxEditor } from './_bbox-editor';

export function ContributionWorkspace({
  initial,
  initialReveal = null,
  onCompleted,
}: {
  initial: BlindWorkspace;
  initialReveal?: RevealResult | null;
  onCompleted?: () => void | Promise<void>;
}) {
  const task = initial.next_task;
  const [reveal, setReveal] = useState(initialReveal);
  const [boxes, setBoxes] = useState<HumanBox[]>(initialReveal?.working_annotation.boxes ?? []);
  const [noGecko, setNoGecko] = useState(initialReveal?.working_annotation.no_gecko ?? false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [completed, setCompleted] = useState(false);
  const [resumeAttempt, setResumeAttempt] = useState(0);

  useEffect(() => {
    if (!task || task.stage === 'blind' || reveal) return;
    let active = true;
    setBusy(true);
    revealYoloPrediction(task.task_id)
      .then((value) => {
        if (!active) return;
        setReveal(value);
        setBoxes(value.working_annotation.boxes);
        setNoGecko(value.working_annotation.no_gecko);
        setMessage('잠긴 사람 박스와 모델 결과를 다시 불러왔어.');
      })
      .catch((error) => {
        if (active) setMessage(error instanceof Error ? error.message : '잠긴 작업을 불러오지 못했어.');
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [reveal, resumeAttempt, task]);

  if (!initial.enabled) return <p className="rounded-xl bg-zinc-100 p-4 text-sm">배정된 게코 bbox 작업이 없어.</p>;
  if (!task) return <p className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">배정 작업을 모두 제출했어.</p>;
  if (completed) return <p className="rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">Owner 검수 후보로 제출했어. 다음 작업을 불러오는 중이야.</p>;
  if (task.stage !== 'blind' && !reveal) {
    return <div className="space-y-3 rounded-xl bg-zinc-100 p-4 text-sm"><p aria-live="polite">{message || '잠긴 사람 박스를 불러오는 중…'}</p><Button disabled={busy} onClick={() => setResumeAttempt((value) => value + 1)} type="button" variant="secondary">잠긴 작업 다시 불러오기</Button></div>;
  }
  const taskId = task.task_id;

  async function lockAndReveal() {
    setBusy(true);
    setMessage('');
    try {
      await submitYoloBlind(taskId, { boxes: noGecko ? [] : boxes, no_gecko: noGecko });
      const value = await revealYoloPrediction(taskId);
      setReveal(value);
      setBoxes(value.working_annotation.boxes);
      setNoGecko(value.working_annotation.no_gecko);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '제출하지 못했어.');
    } finally {
      setBusy(false);
    }
  }

  async function submitRevision() {
    setBusy(true);
    setMessage('');
    try {
      await submitYoloRevision(taskId, { boxes: noGecko ? [] : boxes, no_gecko: noGecko }, reason);
      setMessage('Owner 검수 후보로 제출했어. 승인 전에는 Dataset에 들어가지 않아.');
      setCompleted(true);
      await onCompleted?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '최종 사람 박스를 제출하지 못했어.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between gap-3 text-sm text-zinc-600">
        <span>진행 {initial.completed} / {initial.total}</span>
        <span>{reveal ? '모델 reveal 완료' : 'blind-first · 모델 비공개'}</span>
      </div>
      {reveal ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          <strong>사람 박스</strong>는 초록, <strong>모델 박스</strong>는 주황이야. 모델 {reveal.prediction.model_version} · {reveal.prediction.warning}
        </div>
      ) : null}
      {reveal?.owner_feedback ? <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-900"><strong>Owner 반려 사유:</strong> {reveal.owner_feedback}</p> : null}
      <BboxEditor boxes={boxes} modelFrames={reveal?.prediction.frames} onChange={(value) => { setBoxes(value); setNoGecko(false); }} task={task} />
      <label className="flex items-center gap-2 text-sm"><input checked={noGecko} onChange={(event) => { setNoGecko(event.target.checked); if (event.target.checked) setBoxes([]); }} type="checkbox" />이 frame들에 게코 없음</label>
      {!reveal ? (
        <Button disabled={busy || (!noGecko && boxes.length === 0)} onClick={lockAndReveal} size="lg" type="button">내 박스 잠그고 모델 결과 보기</Button>
      ) : (
        <div className="space-y-3">
          <label className="block space-y-1 text-sm"><span className="font-medium">변경 사유</span><textarea className="min-h-24 w-full rounded-lg border border-zinc-300 p-3" onChange={(event) => setReason(event.target.value)} value={reason} /></label>
          <Button disabled={busy || reason.trim().length < 3 || (!noGecko && boxes.length === 0)} onClick={submitRevision} size="lg" type="button">Owner 검수 후보로 제출</Button>
        </div>
      )}
      {message ? <p aria-live="polite" className="text-sm text-zinc-700">{message}</p> : null}
    </section>
  );
}
