'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  frameAtTime,
  type DetectionFrame,
  type GeckoDetectionResult,
} from '@/lib/yoloDetection';

function Boxes({ frame }: { frame: DetectionFrame | null }) {
  if (!frame) return null;
  return (
    <svg
      aria-label="게코 감지 박스"
      className="pointer-events-none absolute inset-0 h-full w-full"
      preserveAspectRatio="none"
      viewBox="0 0 1 1"
    >
      {frame.detections.map((item, index) => (
        <g key={`${frame.frame_index}-${index}`}>
          <rect
            fill="none"
            height={item.bbox.height}
            stroke="#22c55e"
            strokeWidth="0.006"
            vectorEffect="non-scaling-stroke"
            width={item.bbox.width}
            x={item.bbox.x}
            y={item.bbox.y}
          />
        </g>
      ))}
    </svg>
  );
}

function ResultMeta({ result, frame }: { result: GeckoDetectionResult; frame: DetectionFrame | null }) {
  const processed = useMemo(
    () =>
      new Intl.DateTimeFormat('ko-KR', {
        dateStyle: 'medium',
        timeStyle: 'medium',
        timeZone: 'Asia/Seoul',
      }).format(new Date(result.processed_at)),
    [result.processed_at],
  );
  return (
    <div className="space-y-2 rounded-xl border border-zinc-200 bg-white p-4 text-sm text-zinc-700">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="font-medium text-zinc-500">모델</dt>
        <dd>{result.model_version}</dd>
        <dt className="font-medium text-zinc-500">처리 모드</dt>
        <dd>{result.provider_mode === 'fake' ? '계약 시연용 fake' : 'inference worker'}</dd>
        <dt className="font-medium text-zinc-500">처리시각</dt>
        <dd>{processed}</dd>
        <dt className="font-medium text-zinc-500">현재 confidence</dt>
        <dd>
          {frame && frame.detections.length > 0
            ? frame.detections.map((item) => `${Math.round(item.confidence * 100)}%`).join(', ')
            : '감지 없음'}
        </dd>
      </dl>
      <p className="rounded-lg bg-amber-50 px-3 py-2 font-medium text-amber-900">{result.warning}</p>
      {result.contribution_status === 'candidate_only' ? (
        <p>후보 제공 의사만 표시됐어. 현재 fake 시연은 파일을 저장하지 않으며 사람 GT도 아니야.</p>
      ) : (
        <p>이 업로드는 학습 데이터로 사용되지 않아.</p>
      )}
    </div>
  );
}

export function DetectionOverlay({
  result,
  mediaUrl,
}: {
  result: GeckoDetectionResult;
  mediaUrl: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [visibleFrame, setVisibleFrame] = useState<DetectionFrame | null>(result.frames[0] ?? null);
  const [boxesVisible, setBoxesVisible] = useState(true);

  useEffect(() => {
    if (result.media_kind !== 'video') return;
    let animationId = 0;
    const update = () => {
      const element = videoRef.current;
      if (element) setVisibleFrame(frameAtTime(result.frames, element.currentTime * 1000));
      animationId = window.requestAnimationFrame(update);
    };
    animationId = window.requestAnimationFrame(update);
    return () => window.cancelAnimationFrame(animationId);
  }, [result.frames, result.media_kind]);

  return (
    <section className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
      <div
        className="relative min-w-0 overflow-hidden rounded-xl bg-black"
        data-overlay-kind={result.media_kind}
      >
        {result.media_kind === 'image' ? (
          // eslint-disable-next-line @next/next/no-img-element -- 사용자가 방금 고른 blob URL은 next/image 대상이 아님.
          <img alt="업로드한 게코 감지 대상" className="block h-auto w-full" src={mediaUrl} />
        ) : (
          <video
            ref={videoRef}
            className="block h-auto w-full"
            controls
            playsInline
            src={mediaUrl}
          />
        )}
        {boxesVisible ? <Boxes frame={visibleFrame} /> : null}
        <button className="absolute right-3 top-3 rounded-lg bg-black/75 px-3 py-2 text-xs font-medium text-white" onClick={() => setBoxesVisible((value) => !value)} type="button">{boxesVisible ? '박스 숨기기' : '박스 보기'}</button>
      </div>
      <ResultMeta frame={visibleFrame} result={result} />
    </section>
  );
}
