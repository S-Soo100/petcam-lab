'use client';

import { useRef, useState } from 'react';
import type { MutableRefObject, ReactNode } from 'react';

export function formatReviewVideoTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export type ContainedMediaRect = {
  leftPct: number;
  topPct: number;
  widthPct: number;
  heightPct: number;
};

export function getContainedMediaRect(
  sourceWidth: number,
  sourceHeight: number,
  containerWidth: number,
  containerHeight: number,
): ContainedMediaRect {
  if (![sourceWidth, sourceHeight, containerWidth, containerHeight].every((value) => Number.isFinite(value) && value > 0)) {
    return { leftPct: 0, topPct: 0, widthPct: 100, heightPct: 100 };
  }

  const sourceRatio = sourceWidth / sourceHeight;
  const containerRatio = containerWidth / containerHeight;
  if (sourceRatio >= containerRatio) {
    const heightPct = (containerRatio / sourceRatio) * 100;
    return { leftPct: 0, topPct: (100 - heightPct) / 2, widthPct: 100, heightPct };
  }

  const widthPct = (sourceRatio / containerRatio) * 100;
  return { leftPct: (100 - widthPct) / 2, topPct: 0, widthPct, heightPct: 100 };
}

type ReviewVideoProps = {
  src: string;
  getDownload: () => Promise<{ url: string; filename: string }>;
  videoRef?: MutableRefObject<HTMLVideoElement | null>;
  className?: string;
  mediaClassName?: string;
  autoPlay?: boolean;
  showControls?: boolean;
  overlay?: ReactNode;
  onLoadedMetadata?: () => void;
  onCanPlay?: () => void;
  onError?: () => void;
  onPlay?: () => void;
  onPause?: () => void;
  onSeeking?: () => void;
  onWaiting?: () => void;
  onTimeUpdate?: (currentTime: number) => void;
};

export default function ReviewVideo(props: ReviewVideoProps) {
  const { src } = props;
  return <ReviewVideoInstance key={src} {...props} />;
}

function ReviewVideoInstance({
  src,
  getDownload,
  videoRef: suppliedVideoRef,
  className = '',
  mediaClassName = 'block aspect-video w-full bg-black object-contain',
  autoPlay = true,
  showControls = true,
  overlay,
  onLoadedMetadata,
  onCanPlay,
  onError,
  onPlay,
  onPause,
  onSeeking,
  onWaiting,
  onTimeUpdate,
}: ReviewVideoProps) {
  const internalVideoRef = useRef<HTMLVideoElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const videoRef = suppliedVideoRef ?? internalVideoRef;
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [sourceSize, setSourceSize] = useState({ width: 16, height: 9 });
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(false);
  const overlayRect = getContainedMediaRect(sourceSize.width, sourceSize.height, 16, 9);

  async function togglePlayback() {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      try {
        await video.play();
      } catch {
        setPlaying(false);
      }
    } else {
      video.pause();
    }
  }

  function toggleMuted() {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setMuted(video.muted);
  }

  function seek(nextTime: number) {
    const video = videoRef.current;
    if (!video || !Number.isFinite(nextTime)) return;
    video.currentTime = Math.min(Math.max(0, nextTime), duration || 0);
    setCurrentTime(video.currentTime);
    onTimeUpdate?.(video.currentTime);
  }

  async function openFullscreen() {
    try {
      await wrapperRef.current?.requestFullscreen();
    } catch {
      // 전체화면 지원 여부는 검수 답이나 영상 재생 상태를 바꾸지 않는다.
    }
  }

  async function downloadVideo() {
    if (downloading) return;
    setDownloading(true);
    setDownloadError(false);
    try {
      // 버튼을 누를 때만 권한 API가 attachment signed URL을 새로 발급한다.
      const download = await getDownload();
      const anchor = document.createElement('a');
      anchor.href = download.url;
      anchor.download = download.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch {
      setDownloadError(true);
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div ref={wrapperRef} className={`overflow-hidden rounded-lg bg-black ${className}`}>
      <div className="relative w-full bg-black">
        <video
          ref={(node) => {
            internalVideoRef.current = node;
            if (suppliedVideoRef) suppliedVideoRef.current = node;
            node?.setAttribute('referrerpolicy', 'no-referrer');
          }}
          src={src}
          autoPlay={autoPlay}
          muted
          playsInline
          preload="auto"
          className={mediaClassName}
          onPlay={() => {
            setPlaying(true);
            onPlay?.();
          }}
          onPause={() => {
            setPlaying(false);
            onPause?.();
          }}
          onEnded={() => setPlaying(false)}
          onSeeking={onSeeking}
          onWaiting={onWaiting}
          onTimeUpdate={(event) => {
            setCurrentTime(event.currentTarget.currentTime);
            onTimeUpdate?.(event.currentTarget.currentTime);
          }}
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            setDuration(Number.isFinite(video.duration) ? video.duration : 0);
            setSourceSize({ width: video.videoWidth, height: video.videoHeight });
            setMuted(video.muted);
            onLoadedMetadata?.();
            if (autoPlay) void video.play().catch(() => setPlaying(false));
          }}
          onCanPlay={onCanPlay}
          onError={onError}
        />
        {overlay && (
          <div
            className="pointer-events-none absolute"
            style={{
              left: `${overlayRect.leftPct}%`,
              top: `${overlayRect.topPct}%`,
              width: `${overlayRect.widthPct}%`,
              height: `${overlayRect.heightPct}%`,
            }}
          >
            {overlay}
          </div>
        )}
      </div>
      {showControls ? <div className="flex min-w-0 flex-wrap items-center gap-2 border-t border-zinc-700 bg-zinc-950 px-2 py-2 text-xs text-white">
        <button
          type="button"
          aria-label={playing ? '영상 일시정지' : '영상 재생'}
          className="min-h-11 min-w-11 shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          onClick={() => void togglePlayback()}
        >
          {playing ? '일시정지' : '재생'}
        </button>
        <span className="shrink-0 tabular-nums text-zinc-300">
          {formatReviewVideoTime(currentTime)} / {formatReviewVideoTime(duration)}
        </span>
        <input
          type="range"
          aria-label="영상 재생 위치"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(currentTime, duration || 0)}
          className="order-last w-full flex-none accent-emerald-500 sm:order-none sm:min-w-12 sm:flex-1"
          onChange={(event) => seek(Number(event.target.value))}
        />
        <button
          type="button"
          aria-label={muted ? '소리 켜기' : '음소거'}
          className="min-h-11 min-w-11 shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          onClick={toggleMuted}
        >
          {muted ? '소리 켜기' : '음소거'}
        </button>
        <button
          type="button"
          aria-label="전체화면"
          className="min-h-11 min-w-11 shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          onClick={() => void openFullscreen()}
        >
          전체화면
        </button>
        <button
          type="button"
          aria-label="영상 다운로드"
          disabled={downloading}
          className="min-h-11 min-w-11 shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 disabled:text-zinc-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          onClick={() => void downloadVideo()}
        >
          {downloading ? '받는 중…' : '다운로드'}
        </button>
        {downloadError && (
          <span role="status" className="w-full text-rose-300">다운로드하지 못했어. 잠시 뒤 다시 눌러줘.</span>
        )}
      </div> : null}
    </div>
  );
}
