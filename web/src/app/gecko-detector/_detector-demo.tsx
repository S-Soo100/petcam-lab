'use client';

import { DragEvent, FormEvent, useEffect, useRef, useState } from 'react';

import Button from '@/components/ui/Button';
import { validateDetectionResult, type GeckoDetectionResult } from '@/lib/yoloDetection';
import { DetectionOverlay } from './_detection-overlay';

const ACCEPTED = new Set(['image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'video/webm']);

function localFileError(file: File): string | null {
  if (!ACCEPTED.has(file.type)) return 'JPEG, PNG, WebP, MP4, WebM 파일만 올릴 수 있어.';
  const limit = file.type.startsWith('image/') ? 10 * 1024 * 1024 : 50 * 1024 * 1024;
  if (file.size > limit) return file.type.startsWith('image/') ? '사진은 10 MiB 이하여야 해.' : '영상은 50 MiB 이하여야 해.';
  if (file.size === 0) return '빈 파일은 분석할 수 없어.';
  return null;
}

export function selectDroppedFile(files: ArrayLike<File>): { file: File | null; error: string | null } {
  if (files.length !== 1) return { file: null, error: '한 번에 파일 하나만 올려줘.' };
  return { file: files[0], error: null };
}

export function processingMessage(assistEnabled: boolean): string {
  return assistEnabled
    ? '라벨링 보조 worker에 안전하게 전달하고 있어.'
    : '연구용 감지 worker 계약을 확인하고 있어.';
}

export function DetectorDemo({ assistEnabled = false }: { assistEnabled?: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const [result, setResult] = useState<GeckoDetectionResult | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const previousUrl = useRef<string | null>(null);
  const noCandidateDetections = result !== null
    && result.frames.reduce((sum, frame) => sum + frame.detections.length, 0) === 0;

  useEffect(() => () => {
    if (previousUrl.current) URL.revokeObjectURL(previousUrl.current);
  }, []);

  function selectFile(next: File | null) {
    if (previousUrl.current) URL.revokeObjectURL(previousUrl.current);
    previousUrl.current = null;
    setResult(null);
    setStatus('idle');
    setMessage('');
    if (!next) {
      setFile(null);
      setMediaUrl(null);
      return;
    }
    const error = localFileError(next);
    if (error) {
      setFile(null);
      setMediaUrl(null);
      setStatus('error');
      setMessage(error);
      return;
    }
    const url = URL.createObjectURL(next);
    previousUrl.current = url;
    setFile(next);
    setMediaUrl(url);
  }

  function isFileDrag(event: DragEvent<HTMLLabelElement>) {
    return Array.from(event.dataTransfer.types).includes('Files');
  }

  function handleDragEnter(event: DragEvent<HTMLLabelElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth.current += 1;
    setDragActive(true);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }

  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    if (fileInputRef.current) fileInputRef.current.value = '';
    const dropped = selectDroppedFile(event.dataTransfer.files);
    if (dropped.error) {
      selectFile(null);
      setStatus('error');
      setMessage(dropped.error);
      return;
    }
    selectFile(dropped.file);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setStatus('error');
      setMessage('분석할 파일을 먼저 선택해.');
      return;
    }
    setStatus('loading');
    setMessage(processingMessage(assistEnabled));
    const data = new FormData();
    data.set('media', file);
    data.set('training_consent', String(consent));
    try {
      const response = await fetch('/api/yolo-demo/infer', { method: 'POST', body: data });
      const payload: unknown = await response.json();
      if (!response.ok) {
        const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
          ? String((payload as { detail: unknown }).detail)
          : '분석 요청을 완료하지 못했어.';
        throw new Error(detail);
      }
      const safe = validateDetectionResult(payload);
      if (!safe) throw new Error('분석 결과 형식이 올바르지 않아.');
      setResult(safe);
      setStatus('done');
      setMessage('처리가 끝났어. 박스와 원본을 함께 확인해.');
    } catch (error) {
      setResult(null);
      setStatus('error');
      setMessage(error instanceof Error ? error.message : '분석 요청을 완료하지 못했어.');
    }
  }

  return (
    <div className="space-y-6">
      {assistEnabled ? (
        <aside className="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950">
          <p className="font-semibold">Development-only 라벨링 보조</p>
          <p className="mt-1">
            Development-only 후보 박스야. production 자동판정 모델이 아니야.
            박스가 없어도 게코가 없다는 뜻은 아니야.
          </p>
        </aside>
      ) : null}
      <form className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm" onSubmit={submit}>
        <label
          className={`block space-y-3 rounded-xl border-2 border-dashed p-5 transition-colors ${
            dragActive ? 'border-emerald-500 bg-emerald-50' : 'border-zinc-300 bg-zinc-50'
          }`}
          data-drop-zone="true"
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <span className="block font-semibold text-zinc-900">
            {dragActive ? '여기에 놓아줘' : '사진·영상을 끌어 놓거나 파일 선택'}
          </span>
          <input
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm"
            className="block w-full rounded-lg border border-zinc-300 bg-white p-3 text-sm"
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
            ref={fileInputRef}
            type="file"
          />
          {file ? <span className="block text-sm font-medium text-emerald-800">선택됨: {file.name}</span> : null}
          <span className="block text-xs text-zinc-500">사진 10 MiB, 영상 50 MiB 이하 · 영상은 후속 worker에서 최대 60초를 검증해.</span>
        </label>
        <label className="flex items-start gap-3 rounded-xl bg-zinc-50 p-3 text-sm text-zinc-700">
          <input checked={consent} className="mt-1" onChange={(event) => setConsent(event.target.checked)} type="checkbox" />
          <span>
            <strong className="block text-zinc-900">이 업로드를 연구 데이터 후보로 제공</strong>
            기본은 꺼져 있어. 켜도 즉시 GT나 학습 데이터가 되지 않고 Owner 검수 전 후보로만 표시돼.
          </span>
        </label>
        <Button disabled={status === 'loading'} size="lg" type="submit">
          {status === 'loading' ? '처리 중…' : '게코 찾기'}
        </Button>
        {message ? <p aria-live="polite" className={status === 'error' ? 'text-sm text-red-700' : 'text-sm text-zinc-600'}>{message}</p> : null}
      </form>
      {noCandidateDetections ? (
        <aside className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.
        </aside>
      ) : null}
      {result && mediaUrl ? <DetectionOverlay mediaUrl={mediaUrl} result={result} /> : null}
    </div>
  );
}
