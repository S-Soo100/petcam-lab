'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { MutableRefObject, PointerEvent as ReactPointerEvent, ReactNode } from 'react';

import type { NormalizedBox } from '@/lib/gmeNegativeAudit';

type Point = { x: number; y: number };
type Rect = { left: number; top: number; width: number; height: number };

const MIN_BOX_SIDE = 0.005;

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function stable(value: number): number {
  return Math.round(value * 1_000_000_000_000) / 1_000_000_000_000;
}

export function normalizeDrag(start: Point, end: Point, rect: Rect): NormalizedBox | null {
  if (
    !Number.isFinite(rect.left) ||
    !Number.isFinite(rect.top) ||
    !Number.isFinite(rect.width) ||
    !Number.isFinite(rect.height) ||
    rect.width <= 0 ||
    rect.height <= 0
  ) return null;

  const startX = clamp((start.x - rect.left) / rect.width);
  const startY = clamp((start.y - rect.top) / rect.height);
  const endX = clamp((end.x - rect.left) / rect.width);
  const endY = clamp((end.y - rect.top) / rect.height);
  const box = {
    x: stable(Math.min(startX, endX)),
    y: stable(Math.min(startY, endY)),
    width: stable(Math.abs(endX - startX)),
    height: stable(Math.abs(endY - startY)),
  };
  return box.width >= MIN_BOX_SIDE && box.height >= MIN_BOX_SIDE ? box : null;
}

export function displayedVideoRect(rect: Rect, videoWidth: number, videoHeight: number): Rect {
  if (
    rect.width <= 0 ||
    rect.height <= 0 ||
    !Number.isFinite(videoWidth) ||
    !Number.isFinite(videoHeight) ||
    videoWidth <= 0 ||
    videoHeight <= 0
  ) return rect;

  const elementRatio = rect.width / rect.height;
  const videoRatio = videoWidth / videoHeight;
  if (videoRatio > elementRatio) {
    const height = rect.width / videoRatio;
    return { left: rect.left, top: rect.top + (rect.height - height) / 2, width: rect.width, height };
  }
  const width = rect.height * videoRatio;
  return { left: rect.left + (rect.width - width) / 2, top: rect.top, width, height: rect.height };
}

export default function NormalizedBboxEditor({
  enabled = true,
  videoRef,
  value,
  onChange,
  children,
}: {
  enabled?: boolean;
  videoRef: MutableRefObject<HTMLVideoElement | null>;
  value: NormalizedBox | null;
  onChange: (box: NormalizedBox | null) => void;
  children: ReactNode;
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<SVGSVGElement | null>(null);
  const startRef = useRef<Point | null>(null);
  const [overlayRect, setOverlayRect] = useState<Rect | null>(null);
  const [preview, setPreview] = useState<NormalizedBox | null>(null);
  const [drawing, setDrawing] = useState(enabled && value === null);

  useEffect(() => {
    setDrawing(enabled && value === null);
    setPreview(null);
    startRef.current = null;
  }, [enabled, value]);

  const measure = useCallback(() => {
    const wrapper = wrapperRef.current;
    const video = videoRef.current;
    if (!wrapper || !video) return;
    if (video.videoWidth <= 0 || video.videoHeight <= 0) {
      setOverlayRect(null);
      return;
    }
    const wrapperBox = wrapper.getBoundingClientRect();
    const videoBox = video.getBoundingClientRect();
    const shown = displayedVideoRect(videoBox, video.videoWidth, video.videoHeight);
    setOverlayRect({
      left: shown.left - wrapperBox.left,
      top: shown.top - wrapperBox.top,
      width: shown.width,
      height: shown.height,
    });
  }, [videoRef]);

  useEffect(() => {
    measure();
    const wrapper = wrapperRef.current;
    const video = videoRef.current;
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    if (wrapper) observer?.observe(wrapper);
    if (video) observer?.observe(video);
    window.addEventListener('resize', measure);
    video?.addEventListener('loadedmetadata', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
      video?.removeEventListener('loadedmetadata', measure);
    };
  }, [measure, videoRef]);

  function eventPoint(event: ReactPointerEvent<SVGSVGElement>): Point {
    return { x: event.clientX, y: event.clientY };
  }

  function pointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (!enabled || !drawing || event.button !== 0) return;
    event.preventDefault();
    startRef.current = eventPoint(event);
    setPreview(null);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function pointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (!enabled || !drawing || !startRef.current) return;
    setPreview(normalizeDrag(startRef.current, eventPoint(event), event.currentTarget.getBoundingClientRect()));
  }

  function releasePointer(event: ReactPointerEvent<SVGSVGElement>, commit: boolean) {
    const start = startRef.current;
    startRef.current = null;
    const box = start && commit
      ? normalizeDrag(start, eventPoint(event), event.currentTarget.getBoundingClientRect())
      : null;
    setPreview(null);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
    if (box) {
      onChange(box);
      setDrawing(false);
    }
  }

  const shown = preview ?? value;
  const canDraw = enabled && overlayRect !== null;
  const overlayStyle = overlayRect
    ? { left: overlayRect.left, top: overlayRect.top, width: overlayRect.width, height: overlayRect.height }
    : { left: 0, top: 0, width: 0, height: 0 };

  return (
    <div className="space-y-2">
      <div ref={wrapperRef} className="relative min-w-0">
        {children}
        {enabled && <svg
          ref={overlayRef}
          role="img"
          tabIndex={canDraw && drawing ? 0 : -1}
          aria-label="게코 위치 bbox 그리기 영역"
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          className={`absolute z-10 touch-none ${canDraw && drawing ? 'cursor-crosshair pointer-events-auto' : 'pointer-events-none'}`}
          style={overlayStyle}
          onPointerDown={pointerDown}
          onPointerMove={pointerMove}
          onPointerUp={(event) => releasePointer(event, true)}
          onPointerCancel={(event) => releasePointer(event, false)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              startRef.current = null;
              setPreview(null);
            }
          }}
        >
          {shown && (
            <rect
              x={shown.x}
              y={shown.y}
              width={shown.width}
              height={shown.height}
              fill="rgba(16,185,129,0.12)"
              stroke="#10b981"
              strokeWidth="0.006"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>}
      </div>
      {enabled && <><div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          disabled={!canDraw}
          className="min-h-11 rounded-md border-2 border-zinc-300 bg-white px-3 text-sm font-semibold text-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          onClick={() => {
            onChange(null);
            setPreview(null);
            setDrawing(true);
            requestAnimationFrame(() => overlayRef.current?.focus());
          }}
        >
          bbox 다시 그리기
        </button>
        <button
          type="button"
          className="min-h-11 rounded-md border-2 border-zinc-300 bg-white px-3 text-sm font-semibold text-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 disabled:text-zinc-400"
          disabled={!value}
          onClick={() => {
            onChange(null);
            setPreview(null);
            setDrawing(false);
          }}
        >
          bbox 지우기
        </button>
      </div>
      <p className="text-xs text-zinc-600" aria-live="polite">
        {value ? 'bbox가 선택됐어.' : !canDraw ? '영상 표시 영역을 확인하고 있어.' : drawing ? '영상 위에서 게코를 감싸도록 드래그해.' : 'bbox가 비어 있어.'}
      </p>
      </>}
    </div>
  );
}
