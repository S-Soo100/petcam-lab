'use client';

import { useRef, useState } from 'react';
import type { MutableRefObject } from 'react';

export function formatReviewVideoTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

type ReviewVideoProps = {
  src: string;
  videoRef?: MutableRefObject<HTMLVideoElement | null>;
  className?: string;
  onLoadedMetadata?: () => void;
  onError?: () => void;
};

export default function ReviewVideo({
  src,
  videoRef: suppliedVideoRef,
  className = '',
  onLoadedMetadata,
  onError,
}: ReviewVideoProps) {
  const internalVideoRef = useRef<HTMLVideoElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const videoRef = suppliedVideoRef ?? internalVideoRef;
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

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
  }

  async function openFullscreen() {
    try {
      await wrapperRef.current?.requestFullscreen();
    } catch {
      // 전체화면 지원 여부는 검수 답이나 영상 재생 상태를 바꾸지 않는다.
    }
  }

  return (
    <div ref={wrapperRef} className={`overflow-hidden rounded-lg bg-black ${className}`}>
      <video
        ref={(node) => {
          internalVideoRef.current = node;
          if (suppliedVideoRef) suppliedVideoRef.current = node;
        }}
        src={src}
        autoPlay
        muted
        playsInline
        preload="auto"
        className="block aspect-video w-full bg-black object-contain"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          setDuration(Number.isFinite(video.duration) ? video.duration : 0);
          setMuted(video.muted);
          onLoadedMetadata?.();
          void video.play().catch(() => setPlaying(false));
        }}
        onError={onError}
      />
      <div className="flex min-w-0 items-center gap-2 border-t border-zinc-700 bg-zinc-950 px-2 py-2 text-xs text-white">
        <button
          type="button"
          aria-label={playing ? '영상 일시정지' : '영상 재생'}
          className="shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
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
          className="min-w-12 flex-1 accent-emerald-500"
          onChange={(event) => seek(Number(event.target.value))}
        />
        <button
          type="button"
          aria-label={muted ? '소리 켜기' : '음소거'}
          className="shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          onClick={toggleMuted}
        >
          {muted ? '소리 켜기' : '음소거'}
        </button>
        <button
          type="button"
          aria-label="전체화면"
          className="shrink-0 rounded px-2 py-1 font-semibold hover:bg-zinc-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          onClick={() => void openFullscreen()}
        >
          전체화면
        </button>
      </div>
    </div>
  );
}
