'use client';
import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useDropzone } from 'react-dropzone';
import { SPECIES, type Species } from '@/types';
import Button from '@/components/ui/Button';

// 업로드 흐름 (R2 직접 PUT 패턴):
// 1) /api/upload/sign — 메타 검증 + presigned PUT URL + r2_key 발급
// 2) PUT to R2 (브라우저가 직접) — Vercel 4.5MB body limit 우회 + 함수 실행시간 절감
// 3) /api/upload/finalize — DB INSERT 로 camera_clips 행 생성
//
// 왜 이렇게 나누나?
// - Vercel serverless 는 stateless + body limit 4.5MB. 50MB mp4 직접 받으면 fail.
// - R2 outbound 무료 + 인터넷 → R2 가 인터넷 → Vercel 보다 빠름.
// - 실패 지점 분리: sign 실패(서버 env), R2 실패(네트워크), finalize 실패(DB) 각각 메시지 분리.

export default function UploadPage() {
  const router = useRouter();
  const [species, setSpecies] = useState<Species>('crested_gecko');
  const [file, setFile] = useState<File | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<number>(0); // 0~100
  const [stage, setStage] = useState<'idle' | 'sign' | 'put' | 'finalize'>('idle');

  const onDrop = useCallback((accepted: File[]) => {
    setError(null);
    const f = accepted[0];
    if (!f) return;
    setFile(f);
    setDuration(null);
    const url = URL.createObjectURL(f);
    const v = document.createElement('video');
    v.preload = 'metadata';
    v.onloadedmetadata = () => {
      setDuration(v.duration);
      URL.revokeObjectURL(url);
    };
    v.onerror = () => {
      setError('영상 메타데이터 읽기 실패');
      URL.revokeObjectURL(url);
    };
    v.src = url;
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'video/mp4': ['.mp4'] },
    multiple: false,
    maxFiles: 1,
  });

  // R2 PUT 진행률을 보려면 fetch 가 아니라 XHR 필요 (fetch 는 ReadableStream upload 진행률
  // 표준 미정착 + Safari 미지원). 1차에선 단순 PUT.
  async function uploadToR2(putUrl: string, f: File): Promise<void> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', putUrl);
      xhr.setRequestHeader('Content-Type', 'video/mp4');
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          setProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(new Error(`R2 PUT 실패 ${xhr.status}: ${xhr.responseText.slice(0, 200)}`));
      };
      xhr.onerror = () => reject(new Error('R2 PUT 네트워크 오류'));
      xhr.send(f);
    });
  }

  async function submit() {
    if (!file || duration === null) return;
    setUploading(true);
    setError(null);
    setProgress(0);

    try {
      // 1) sign
      setStage('sign');
      const signResp = await fetch('/api/upload/sign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          size: file.size,
          species,
          duration_sec: duration,
        }),
      });
      if (!signResp.ok) {
        const j = await signResp.json().catch(() => ({}));
        throw new Error(j.error ?? `sign 실패 (${signResp.status})`);
      }
      const { put_url, r2_key } = (await signResp.json()) as {
        put_url: string;
        r2_key: string;
      };

      // 2) PUT to R2
      setStage('put');
      await uploadToR2(put_url, file);

      // 3) finalize
      setStage('finalize');
      const finResp = await fetch('/api/upload/finalize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          r2_key,
          species,
          duration_sec: duration,
          file_size: file.size,
          filename: file.name,
        }),
      });
      if (!finResp.ok) {
        const j = await finResp.json().catch(() => ({}));
        throw new Error(j.error ?? `finalize 실패 (${finResp.status})`);
      }

      router.push('/queue');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setUploading(false);
      setStage('idle');
    }
  }

  const stageLabel: Record<typeof stage, string> = {
    idle: '업로드 → 라벨 큐',
    sign: '서명 중...',
    put: `업로드 중... ${progress}%`,
    finalize: '저장 중...',
  };

  return (
    <main className="mx-auto max-w-xl px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">F1 — 영상 업로드</h1>
        <p className="text-sm text-zinc-500">mp4 (≤50MB) → R2 직접 업로드 → 라벨 큐</p>
      </div>

      <div className="space-y-2">
        <label className="block text-xs font-medium uppercase tracking-wide text-zinc-500">
          종
        </label>
        <select
          value={species}
          onChange={(e) => setSpecies(e.target.value as Species)}
          className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm focus:border-zinc-400 focus:outline-none"
        >
          {SPECIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div
        {...getRootProps()}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
          isDragActive
            ? 'border-blue-400 bg-blue-50'
            : file
              ? 'border-zinc-300 bg-zinc-50'
              : 'border-zinc-300 hover:border-zinc-400 hover:bg-zinc-50'
        }`}
      >
        <input {...getInputProps()} />
        {file ? (
          <div className="space-y-1">
            <div className="font-mono text-sm text-zinc-900">{file.name}</div>
            <div className="text-xs text-zinc-500">
              {(file.size / 1024 / 1024).toFixed(1)}MB
              {duration !== null && ` · ${duration.toFixed(1)}s`}
            </div>
            <div className="pt-2 text-xs text-zinc-400">다른 파일 선택하려면 클릭/드롭</div>
          </div>
        ) : (
          <div className="space-y-1 text-sm text-zinc-500">
            <div>mp4 파일을 끌어다 놓거나 클릭해서 선택</div>
            <div className="text-xs text-zinc-400">최대 50MB</div>
          </div>
        )}
      </div>

      {stage === 'put' && (
        <div className="h-2 overflow-hidden rounded-full bg-zinc-200">
          <div
            className="h-full bg-emerald-500 transition-[width]"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <Button
        size="lg"
        onClick={submit}
        disabled={!file || duration === null || uploading}
      >
        {stageLabel[stage]}
      </Button>
    </main>
  );
}
