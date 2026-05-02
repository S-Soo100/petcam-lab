'use client';
import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useDropzone } from 'react-dropzone';
import { SPECIES, type Species } from '@/types';
import Button from '@/components/ui/Button';

export default function UploadPage() {
  const router = useRouter();
  const [species, setSpecies] = useState<Species>('crested_gecko');
  const [file, setFile] = useState<File | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

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

  async function submit() {
    if (!file || duration === null) return;
    setUploading(true);
    setError(null);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('species', species);
    fd.append('duration_sec', String(duration));
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      setError(j.error ?? `업로드 실패 (${res.status})`);
      setUploading(false);
      return;
    }
    router.push('/queue');
  }

  return (
    <main className="mx-auto max-w-xl px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">F1 — 영상 업로드</h1>
        <p className="text-sm text-zinc-500">mp4 (≤50MB) → 자동으로 라벨 큐에 진입</p>
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
        {uploading ? '업로드 중...' : '업로드 → 라벨 큐'}
      </Button>
    </main>
  );
}
