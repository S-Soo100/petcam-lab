import { describe, expect, it } from 'vitest';
import {
  decodeQueueCursor,
  encodeQueueCursor,
  InvalidQueueCursorError,
} from './labelingQueueCursor';

const POSITION = {
  startedAt: '2026-07-22T01:02:03.456Z',
  id: '11111111-1111-4111-8111-111111111111',
};

describe('labelingQueueCursor', () => {
  it('round-trips a URL-safe version 1 cursor', () => {
    const encoded = encodeQueueCursor(POSITION);
    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeQueueCursor(encoded)).toEqual(POSITION);
  });

  it.each([
    'not-base64!',
    Buffer.from(JSON.stringify({ v: 2, t: POSITION.startedAt, id: POSITION.id })).toString('base64url'),
    Buffer.from(JSON.stringify({ v: 1, t: 'bad', id: POSITION.id })).toString('base64url'),
    Buffer.from(JSON.stringify({ v: 1, t: POSITION.startedAt, id: 'bad' })).toString('base64url'),
  ])('rejects malformed cursor %s', (raw) => {
    expect(() => decodeQueueCursor(raw)).toThrow(InvalidQueueCursorError);
  });

  it('maps null to the first page', () => {
    expect(decodeQueueCursor(null)).toBeNull();
  });
});
