'use client';

import { DragEvent, FormEvent, useEffect, useRef, useState } from 'react';

import Button from '@/components/ui/Button';
import { getSupabaseBrowser } from '@/lib/supabaseBrowser';
import { validateDetectionResult, type GeckoDetectionResult } from '@/lib/yoloDetection';
import { DetectionOverlay } from '@/app/gecko-detector/_detection-overlay';

const ACCEPTED = new Set(['image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'video/webm']);
const MODEL_VERSION = 'yolo26n-owner-dataset-v2.5-warm-start+2b128f105e89';

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

function fileError(file: File): string | null {
  if (!ACCEPTED.has(file.type)) return 'JPEG, PNG, WebP, MP4, WebM 파일만 올릴 수 있어.';
  if (file.size === 0) return '빈 파일은 분석할 수 없어.';
  const limit = file.type.startsWith('image/') ? 10 * 1024 * 1024 : 50 * 1024 * 1024;
  if (file.size > limit) {
    return file.type.startsWith('image/')
      ? '사진은 10 MiB 이하여야 해.'
      : '영상은 50 MiB 이하여야 해.';
  }
  return null;
}

export async function requestOwnerYoloPreview(
  file: File,
  accessToken: string,
  fetchImpl: FetchLike = fetch,
): Promise<GeckoDetectionResult> {
  const data = new FormData();
  data.set('media', file);
  // Owner Preview에서는 prediction을 학습 후보로 바꾸는 선택 자체를 제공하지 않는다.
  data.set('training_consent', 'false');
  const response = await fetchImpl('/api/yolo-owner/preview/infer', {
    method: 'POST',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    body: data,
  });
  const payload: unknown = await response.json();
  if (!response.ok) {
    const detail = typeof payload === 'object' && payload !== null && 'detail' in payload
      ? String((payload as { detail: unknown }).detail)
      : 'Owner Preview 요청을 완료하지 못했어.';
    throw new Error(detail);
  }
  const result = validateDetectionResult(payload);
  if (
    !result
    || result.model_version !== MODEL_VERSION
    || result.threshold !== 0.20
    || result.development_only !== true
    || result.usage_scope !== 'owner_preview_bbox_suggestion_only'
    || result.contribution_status !== 'not_requested'
  ) {
    throw new Error('Owner Preview 모델 identity가 올바르지 않아.');
  }
  return result;
}

export function OwnerYoloV25Preview() {
  const [file, setFile] = useState<File | null>(null);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [result, setResult] = useState<GeckoDetectionResult | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousUrl = useRef<string | null>(null);
  const noDetections = result !== null
    && result.frames.every((frame) => frame.detections.length === 0);

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
    const error = fileError(next);
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

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    if (inputRef.current) inputRef.current.value = '';
    if (event.dataTransfer.files.length !== 1) {
      selectFile(null);
      setStatus('error');
      setMessage('한 번에 파일 하나만 올려줘.');
      return;
    }
    selectFile(event.dataTransfer.files[0]);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) {
      setStatus('error');
      setMessage('분석할 파일을 먼저 선택해.');
      return;
    }
    setStatus('loading');
    setMessage('격리된 v2.5 Owner Preview worker에 전달하고 있어.');
    try {
      const { data } = await getSupabaseBrowser().auth.getSession();
      const next = await requestOwnerYoloPreview(file, data.session?.access_token ?? '');
      setResult(next);
      setStatus('done');
      setMessage('bbox 제안을 표시했어. 사람 정답과 별도로 직접 확인해.');
    } catch (error) {
      setResult(null);
      setStatus('error');
      setMessage(error instanceof Error ? error.message : 'Owner Preview 요청을 완료하지 못했어.');
    }
  }

  return (
    <div className="space-y-6">
      <aside className="space-y-2 rounded-2xl border border-violet-300 bg-violet-50 p-5 text-sm text-violet-950">
        <p className="font-semibold uppercase tracking-wide">Development-only · Owner Preview</p>
        <p><strong>YOLO26n v2.5 warm-start</strong> · threshold 0.20</p>
        <p>
          regression-only old distribution 결과야. future holdout 통과 전에는 팀원 기본 모델,
          GME/Gecko Vision Gate, production 모델로 승격할 수 없어.
        </p>
        <p className="font-medium">
          prediction은 GT가 아니야. 자동 저장·자동 승인·Dataset 추가·학습 반영이 전부 꺼져 있어.
        </p>
      </aside>

      <form className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm" onSubmit={submit}>
        <label
          className={`block space-y-3 rounded-xl border-2 border-dashed p-5 transition-colors ${
            dragActive ? 'border-violet-500 bg-violet-50' : 'border-zinc-300 bg-zinc-50'
          }`}
          onDragEnter={(event) => {
            if (!isFileDrag(event)) return;
            event.preventDefault();
            dragDepth.current += 1;
            setDragActive(true);
          }}
          onDragLeave={(event) => {
            if (!isFileDrag(event)) return;
            event.preventDefault();
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (dragDepth.current === 0) setDragActive(false);
          }}
          onDragOver={(event) => {
            if (!isFileDrag(event)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
          }}
          onDrop={onDrop}
        >
          <span className="block font-semibold text-zinc-900">
            {dragActive ? '여기에 놓아줘' : '사진·영상을 끌어 놓거나 파일 선택'}
          </span>
          <input
            accept="image/jpeg,image/png,image/webp,video/mp4,video/webm"
            className="block w-full rounded-lg border border-zinc-300 bg-white p-3 text-sm"
            onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
            ref={inputRef}
            type="file"
          />
          {file ? <span className="block text-sm font-medium text-violet-800">선택됨: {file.name}</span> : null}
          <span className="block text-xs text-zinc-500">
            사진 10 MiB, 영상 50 MiB 이하 · 영상은 최대 60초야.
          </span>
        </label>
        <Button disabled={status === 'loading'} size="lg" type="submit">
          {status === 'loading' ? '처리 중…' : 'v2.5 bbox 제안 보기'}
        </Button>
        {message ? (
          <p aria-live="polite" className={status === 'error' ? 'text-sm text-red-700' : 'text-sm text-zinc-600'}>
            {message}
          </p>
        ) : null}
      </form>

      {noDetections ? (
        <aside className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          후보 박스를 찾지 못했어. 게코 없음 판정이 아니니 직접 확인해줘.
        </aside>
      ) : null}
      {result && mediaUrl ? <DetectionOverlay mediaUrl={mediaUrl} result={result} /> : null}
    </div>
  );
}
