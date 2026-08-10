import 'server-only';

import { NextResponse } from 'next/server';

import { mapBlindWorkspace, type BlindWorkspace } from './yoloContribution';
import { mapYoloOwnerOverview, type YoloOwnerOverview } from './yoloOwner';

function errorCode(value: unknown): string | null {
  if (typeof value !== 'object' || value === null || !('code' in value)) return null;
  return typeof (value as { code: unknown }).code === 'string'
    ? (value as { code: string }).code
    : null;
}

export function yoloContributionRpcError(value: unknown): NextResponse | null {
  const code = errorCode(value);
  if (code === '22023') return NextResponse.json({ detail: '요청 값이 올바르지 않아.' }, { status: 400 });
  if (code === 'PT403') return NextResponse.json({ detail: 'forbidden' }, { status: 403 });
  if (code === 'PT404') return NextResponse.json({ detail: '작업을 찾을 수 없어.' }, { status: 404 });
  if (code === 'PT409' || code === 'PT410') {
    return NextResponse.json({ detail: '현재 작업 단계에서는 처리할 수 없어.' }, { status: 409 });
  }
  return null;
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('invalid yolo media projection');
  }
  return value as Record<string, unknown>;
}

function mediaRef(value: unknown): string {
  if (typeof value !== 'string' || value.length < 1 || value.length > 1000) {
    throw new Error('invalid yolo media ref');
  }
  return value;
}

export async function mapSignedBlindWorkspace(
  value: unknown,
  sign: (ref: string) => Promise<string>,
): Promise<BlindWorkspace> {
  const raw = record(value);
  if (raw.next_task === null) return mapBlindWorkspace(raw);
  const task = record(raw.next_task);
  const mediaUrl = await sign(mediaRef(task.media_ref));
  return mapBlindWorkspace({ ...raw, next_task: { ...task, media_url: mediaUrl } });
}

export async function mapSignedYoloOwnerOverview(
  value: unknown,
  sign: (ref: string) => Promise<string>,
): Promise<YoloOwnerOverview> {
  const raw = record(value);
  if (!Array.isArray(raw.reviews) || raw.reviews.length > 100) {
    throw new Error('invalid yolo owner reviews');
  }
  const reviews = await Promise.all(raw.reviews.map(async (item) => {
    const review = record(item);
    return { ...review, media_url: await sign(mediaRef(review.media_ref)) };
  }));
  return mapYoloOwnerOverview({ ...raw, reviews });
}
