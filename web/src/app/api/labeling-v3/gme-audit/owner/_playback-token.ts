import 'server-only';

import { createCipheriv, createDecipheriv, createHmac, randomBytes } from 'node:crypto';

const PREFIX = 'gma1.';
const VERSION = 1;
const PURPOSE = 'gme-owner-audit-media';
const KEY_DOMAIN = 'petcam-lab:gme-owner-audit-media:key:v1';
const AAD = Buffer.from('petcam-lab:gme-owner-audit-media:token:v1', 'utf8');
const NONCE_BYTES = 12;
const TAG_BYTES = 16;
const FRAME_BYTES = 256;
const LENGTH_BYTES = 2;
const PACKED_BYTES = NONCE_BYTES + FRAME_BYTES + TAG_BYTES;
const ENCODED_BYTES = Buffer.alloc(PACKED_BYTES).toString('base64url').length;
const TOKEN_LENGTH = PREFIX.length + ENCODED_BYTES;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export const OWNER_PLAYBACK_MAX_TTL_SEC = 300;

export class InvalidOwnerPlaybackTokenError extends Error {
  constructor() {
    super('invalid_owner_playback_token');
    this.name = 'InvalidOwnerPlaybackTokenError';
  }
}

function playbackKey(): Buffer {
  const secret = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!secret) throw new Error('Owner playback token secret is unavailable');
  return createHmac('sha256', secret).update(KEY_DOMAIN).digest();
}

export function issueOwnerPlaybackToken(
  itemId: string,
  ownerUserId: string,
  ttlSec = OWNER_PLAYBACK_MAX_TTL_SEC,
  nowMs = Date.now(),
): string {
  if (
    !UUID.test(itemId)
    || !UUID.test(ownerUserId)
    || !Number.isInteger(ttlSec)
    || ttlSec < 1
    || ttlSec > OWNER_PLAYBACK_MAX_TTL_SEC
    || !Number.isFinite(nowMs)
  ) throw new Error('Owner playback token input is invalid');
  const payload = Buffer.from(JSON.stringify({
    v: VERSION,
    p: PURPOSE,
    i: itemId,
    u: ownerUserId,
    e: Math.floor(nowMs / 1000) + ttlSec,
  }), 'utf8');
  if (payload.length === 0 || payload.length > FRAME_BYTES - LENGTH_BYTES) {
    throw new Error('Owner playback token payload is invalid');
  }
  const frame = Buffer.alloc(FRAME_BYTES);
  frame.writeUInt16BE(payload.length, 0);
  payload.copy(frame, LENGTH_BYTES);
  const nonce = randomBytes(NONCE_BYTES);
  const cipher = createCipheriv('aes-256-gcm', playbackKey(), nonce);
  cipher.setAAD(AAD);
  const ciphertext = Buffer.concat([cipher.update(frame), cipher.final()]);
  return `${PREFIX}${Buffer.concat([nonce, ciphertext, cipher.getAuthTag()]).toString('base64url')}`;
}

export function verifyOwnerPlaybackToken(
  token: string,
  routeItemId: string,
  nowMs = Date.now(),
): { ownerUserId: string } {
  try {
    if (
      typeof token !== 'string'
      || token.length !== TOKEN_LENGTH
      || !token.startsWith(PREFIX)
      || !UUID.test(routeItemId)
      || !Number.isFinite(nowMs)
    ) throw new InvalidOwnerPlaybackTokenError();
    const encoded = token.slice(PREFIX.length);
    if (encoded.length !== ENCODED_BYTES || !/^[A-Za-z0-9_-]+$/.test(encoded)) {
      throw new InvalidOwnerPlaybackTokenError();
    }
    const packed = Buffer.from(encoded, 'base64url');
    if (packed.length !== PACKED_BYTES || packed.toString('base64url') !== encoded) {
      throw new InvalidOwnerPlaybackTokenError();
    }
    const nonce = packed.subarray(0, NONCE_BYTES);
    const ciphertext = packed.subarray(NONCE_BYTES, -TAG_BYTES);
    const tag = packed.subarray(-TAG_BYTES);
    const decipher = createDecipheriv('aes-256-gcm', playbackKey(), nonce);
    decipher.setAAD(AAD);
    decipher.setAuthTag(tag);
    const frame = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    if (frame.length !== FRAME_BYTES) throw new InvalidOwnerPlaybackTokenError();
    const payloadLength = frame.readUInt16BE(0);
    if (payloadLength === 0 || payloadLength > FRAME_BYTES - LENGTH_BYTES) {
      throw new InvalidOwnerPlaybackTokenError();
    }
    const payloadEnd = LENGTH_BYTES + payloadLength;
    const payload = frame.subarray(LENGTH_BYTES, payloadEnd);
    if (frame.subarray(payloadEnd).some((byte) => byte !== 0)) {
      throw new InvalidOwnerPlaybackTokenError();
    }
    const value = JSON.parse(payload.toString('utf8')) as Record<string, unknown>;
    if (!Buffer.from(JSON.stringify(value), 'utf8').equals(payload)) {
      throw new InvalidOwnerPlaybackTokenError();
    }
    const keys = Object.keys(value);
    if (
      keys.length !== 5
      || keys.some((key, index) => key !== ['v', 'p', 'i', 'u', 'e'][index])
      || value.v !== VERSION
      || value.p !== PURPOSE
      || value.i !== routeItemId
      || typeof value.u !== 'string'
      || !UUID.test(value.u)
      || !Number.isInteger(value.e)
    ) throw new InvalidOwnerPlaybackTokenError();
    const nowSec = Math.floor(nowMs / 1000);
    if ((value.e as number) <= nowSec || (value.e as number) > nowSec + OWNER_PLAYBACK_MAX_TTL_SEC) {
      throw new InvalidOwnerPlaybackTokenError();
    }
    return { ownerUserId: value.u };
  } catch (error) {
    if (error instanceof InvalidOwnerPlaybackTokenError) throw error;
    throw new InvalidOwnerPlaybackTokenError();
  }
}
