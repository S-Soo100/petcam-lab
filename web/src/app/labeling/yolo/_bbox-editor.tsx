'use client';

import { KeyboardEvent, PointerEvent, useRef, useState } from 'react';

import Button from '@/components/ui/Button';
import { createBox, moveBox, resizeBox, type Point, type ResizeHandle } from '@/lib/yoloBboxEditor';
import type { BlindTask, HumanBox } from '@/lib/yoloContribution';
import type { DetectionFrame } from '@/lib/yoloDetection';

import ReviewVideo from '../_review-video';

function point(event: PointerEvent<HTMLDivElement>, element: HTMLDivElement): Point {
  const rect = element.getBoundingClientRect();
  return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
}

type DragOperation =
  | { kind: 'create'; start: Point }
  | { kind: 'move'; index: number; last: Point }
  | { kind: 'resize'; index: number; handle: ResizeHandle; last: Point };

const HANDLE_POSITION: Record<ResizeHandle, string> = {
  nw: '-left-2 -top-2 cursor-nwse-resize',
  ne: '-right-2 -top-2 cursor-nesw-resize',
  sw: '-bottom-2 -left-2 cursor-nesw-resize',
  se: '-bottom-2 -right-2 cursor-nwse-resize',
};

export function BboxEditor({
  task,
  boxes,
  modelFrames = [],
  onChange,
  readOnly = false,
  ariaLabel = '게코 박스를 드래그해서 그리는 영역',
}: {
  task: BlindTask;
  boxes: HumanBox[];
  modelFrames?: DetectionFrame[];
  onChange: (boxes: HumanBox[]) => void;
  readOnly?: boolean;
  ariaLabel?: string;
}) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const dragRef = useRef<DragOperation | null>(null);
  const [position, setPosition] = useState(0);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const frame = task.frame_manifest[position];
  const human = boxes
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item.frame_index === frame.frame_index);
  const model = modelFrames.find((item) => item.frame_index === frame.frame_index)?.detections ?? [];

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (readOnly) return;
    if (!surfaceRef.current) return;
    setSelectedIndex(null);
    dragRef.current = { kind: 'create', start: point(event, surfaceRef.current) };
    surfaceRef.current.setPointerCapture(event.pointerId);
  }

  function startExistingDrag(
    event: PointerEvent<HTMLDivElement>,
    index: number,
    handle?: ResizeHandle,
  ) {
    if (readOnly || !surfaceRef.current) return;
    event.stopPropagation();
    setSelectedIndex(index);
    const last = point(event, surfaceRef.current);
    dragRef.current = handle
      ? { kind: 'resize', index, handle, last }
      : { kind: 'move', index, last };
    surfaceRef.current.setPointerCapture(event.pointerId);
  }

  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.kind === 'create' || !surfaceRef.current) return;
    const current = point(event, surfaceRef.current);
    const dx = current.x - drag.last.x;
    const dy = current.y - drag.last.y;
    const next = boxes.map((item, index) => {
      if (index !== drag.index) return item;
      return {
        ...item,
        bbox: drag.kind === 'move'
          ? moveBox(item.bbox, dx, dy)
          : resizeBox(item.bbox, drag.handle, dx, dy),
      };
    });
    drag.last = current;
    onChange(next);
  }

  function pointerUp(event: PointerEvent<HTMLDivElement>) {
    if (readOnly) return;
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || !surfaceRef.current) return;
    if (drag.kind === 'create') {
      const bbox = createBox(drag.start, point(event, surfaceRef.current));
      if (bbox) {
        onChange([...boxes, { frame_index: frame.frame_index, bbox }]);
        setSelectedIndex(boxes.length);
      }
    }
    if (surfaceRef.current.hasPointerCapture(event.pointerId)) {
      surfaceRef.current.releasePointerCapture(event.pointerId);
    }
  }

  function keyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (readOnly) return;
    if (event.key === 'Escape') {
      setSelectedIndex(null);
      dragRef.current = null;
      return;
    }
    if ((event.key === 'Delete' || event.key === 'Backspace') && selectedIndex !== null) {
      event.preventDefault();
      onChange(boxes.filter((_item, index) => index !== selectedIndex));
      setSelectedIndex(null);
    }
  }

  return (
    <div className="space-y-3">
      <div
        className="relative select-none overflow-hidden rounded-xl bg-black"
      >
        {task.media_kind === 'image' ? (
          // eslint-disable-next-line @next/next/no-img-element -- task media URL은 runtime 원본이라 next/image 최적화 대상이 아님.
          <img alt="bbox 라벨링 대상" className="pointer-events-none block h-auto w-full" src={task.media_url} />
        ) : (
          <ReviewVideo
            autoPlay={false}
            className="rounded-none"
            getDownload={async () => ({ url: task.media_url, filename: `yolo-task-${task.task_id}.mp4` })}
            showControls={false}
            mediaClassName="pointer-events-none block h-auto w-full bg-black"
            onLoadedMetadata={() => {
              if (videoRef.current) videoRef.current.currentTime = frame.timestamp_ms / 1000;
            }}
            src={`${task.media_url}#t=${frame.timestamp_ms / 1000}`}
            videoRef={videoRef}
          />
        )}
        <div
          ref={surfaceRef}
          aria-label={ariaLabel}
          className={`absolute inset-0 ${readOnly ? 'pointer-events-none' : 'touch-none'}`}
          onPointerDown={readOnly ? undefined : pointerDown}
          onPointerMove={readOnly ? undefined : pointerMove}
          onPointerUp={readOnly ? undefined : pointerUp}
          onKeyDown={readOnly ? undefined : keyDown}
          role={readOnly ? 'img' : 'application'}
          tabIndex={readOnly ? undefined : 0}
        >
          {model.map((item, index) => (
            <div key={`model-${index}`} className="pointer-events-none absolute border-2 border-amber-400" style={{ left: `${item.bbox.x * 100}%`, top: `${item.bbox.y * 100}%`, width: `${item.bbox.width * 100}%`, height: `${item.bbox.height * 100}%` }} />
          ))}
          {human.map(({ item, index }, framePosition) => (
            <div
              aria-label={readOnly ? undefined : `사람 박스 ${framePosition + 1} 선택 및 이동`}
              className={`absolute border-2 border-emerald-400 ${readOnly ? 'pointer-events-none' : 'cursor-move'} ${selectedIndex === index ? 'ring-2 ring-white' : ''}`}
              key={`human-${index}`}
              onKeyDown={readOnly ? undefined : (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedIndex(index);
                }
                if (event.key === 'Delete' || event.key === 'Backspace') {
                  event.preventDefault();
                  onChange(boxes.filter((_item, itemIndex) => itemIndex !== index));
                  setSelectedIndex(null);
                }
              }}
              onPointerDown={readOnly ? undefined : (event) => startExistingDrag(event, index)}
              role={readOnly ? undefined : 'button'}
              tabIndex={readOnly ? undefined : 0}
              style={{ left: `${item.bbox.x * 100}%`, top: `${item.bbox.y * 100}%`, width: `${item.bbox.width * 100}%`, height: `${item.bbox.height * 100}%` }}
            >
              {!readOnly && selectedIndex === index ? (Object.keys(HANDLE_POSITION) as ResizeHandle[]).map((handle) => (
                <div
                  aria-label={`${handle} 크기 조절`}
                  className={`absolute h-4 w-4 rounded-full border border-white bg-emerald-500 ${HANDLE_POSITION[handle]}`}
                  key={handle}
                  onPointerDown={(event) => startExistingDrag(event, index, handle)}
                  role="button"
                />
              )) : null}
            </div>
          ))}
        </div>
      </div>
      {!readOnly ? <p className="text-xs text-zinc-500">박스를 선택해 드래그로 이동하고 모서리로 크기를 바꿔. Enter로 선택, Delete/Backspace로 삭제, Escape로 선택 해제할 수 있어.</p> : null}
      {task.media_kind === 'video' ? (
        <div className="flex items-center justify-between gap-2 text-sm">
          <Button disabled={position === 0} onClick={() => { setSelectedIndex(null); setPosition((value) => value - 1); }} type="button" variant="secondary">이전 frame</Button>
          <span>{position + 1} / {task.frame_manifest.length} · {frame.timestamp_ms}ms</span>
          <Button disabled={position === task.frame_manifest.length - 1} onClick={() => { setSelectedIndex(null); setPosition((value) => value + 1); }} type="button" variant="secondary">다음 frame</Button>
        </div>
      ) : null}
      {!readOnly ? <ul className="space-y-1 text-sm">
        {human.map(({ index: globalIndex }, index) => {
          return (
            <li className="flex items-center justify-between rounded-lg bg-zinc-100 px-3 py-2" key={`row-${index}`}>
              <span>사람 박스 {index + 1}</span>
              <button className="text-red-700 underline" onClick={() => onChange(boxes.filter((_box, itemIndex) => itemIndex !== globalIndex))} type="button">삭제</button>
            </li>
          );
        })}
      </ul> : null}
    </div>
  );
}
