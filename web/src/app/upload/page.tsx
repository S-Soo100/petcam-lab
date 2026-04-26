'use client';
import { useCallback, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useDropzone } from 'react-dropzone';
import { SPECIES, type Species } from '@/types';

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
    // 클라이언트에서 video 메타데이터로 duration 추출 (서버에 ffprobe 의존 없이).
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
    <main className="mx-auto max-w-xl p-8 space-y-6">
      <h1 className="text-2xl font-bold">F1 — 영상 업로드</h1>

      <div>
        <label className="block text-sm mb-1 font-medium">종</label>
        <select
          value={species}
          onChange={(e) => setSpecies(e.target.value as Species)}
          className="border rounded px-2 py-1 w-full"
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
        className={`border-2 border-dashed rounded p-8 text-center cursor-pointer transition-colors ${
          isDragActive ? 'bg-blue-50 border-blue-400' : 'border-gray-300 hover:border-gray-400'
        }`}
      >
        <input {...getInputProps()} />
        {file ? (
          <div className="text-sm">
            <div className="font-mono">{file.name}</div>
            <div className="text-gray-500">
              {(file.size / 1024 / 1024).toFixed(1)}MB
              {duration !== null && ` · ${duration.toFixed(1)}s`}
            </div>
          </div>
        ) : (
          <div className="text-gray-500">mp4 파일을 끌어다 놓거나 클릭해서 선택</div>
        )}
      </div>

      {error && <div className="text-red-600 text-sm">{error}</div>}

      <button
        type="button"
        onClick={submit}
        disabled={!file || duration === null || uploading}
        className="bg-blue-600 text-white rounded px-4 py-2 disabled:opacity-40"
      >
        {uploading ? '업로드 중...' : '업로드 → 라벨 큐로'}
      </button>
    </main>
  );
}
