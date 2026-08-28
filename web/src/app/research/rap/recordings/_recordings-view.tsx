import type { RapMode, RapRecordingSummary } from '@/lib/rapRecordings';

type Coverage = { expected: number; captured: number; uploaded: number; failed: number; missing: number };

const STATUS_LABEL: Record<string, string> = {
  pending: '업로드 대기',
  uploading: '업로드 중',
  uploaded: '업로드 완료',
  upload_failed: '업로드 실패',
  integrity_conflict: '무결성 충돌',
  capture_failed: '녹화 실패',
};

export function RecordingsView({
  mode,
  coverage,
  items,
  onSelect,
}: {
  mode: RapMode;
  coverage: Coverage | null;
  items: RapRecordingSummary[];
  onSelect?: (id: string) => void;
}) {
  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-zinc-200 bg-white p-4 shadow-sm">
        <h2 className="font-semibold text-zinc-900">{mode === 'production' ? '야간 실제 녹화' : '테스트 녹화'}</h2>
        {mode === 'production' && coverage ? (
          <div className="mt-2 flex flex-wrap gap-3 text-sm text-zinc-600">
            <strong className="text-emerald-700">{coverage.expected}개 중 {coverage.uploaded}개 업로드</strong>
            <span>수집 {coverage.captured}</span><span>실패 {coverage.failed}</span><span>누락 {coverage.missing}</span>
          </div>
        ) : null}
      </div>
      {items.length === 0 ? <p className="rounded-xl bg-zinc-100 p-4 text-sm text-zinc-500">조건에 맞는 녹화가 없어.</p> : null}
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => {
          const status = item.capture_status === 'capture_failed' ? 'capture_failed' : item.upload_status;
          return (
            <li key={item.id}>
              <button type="button" onClick={() => onSelect?.(item.id)} className="w-full rounded-xl border border-zinc-200 bg-white p-4 text-left shadow-sm hover:border-emerald-400">
                <div className="flex items-center justify-between gap-2">
                  <strong>{item.camera_key}</strong>
                  <span className={status === 'uploaded' ? 'text-xs text-emerald-700' : 'text-xs text-rose-700'}>{STATUS_LABEL[status] ?? '상태 확인 필요'}</span>
                </div>
                <time className="mt-2 block text-sm text-zinc-600">{new Date(item.scheduled_start_utc).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })}</time>
                <p className="mt-1 text-xs text-zinc-500">{Math.round(item.duration_sec / 60)}분 · {item.width}×{item.height} · {item.codec.toUpperCase()}</p>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
