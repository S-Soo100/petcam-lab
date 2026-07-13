import { afterEach, describe, expect, it, vi } from 'vitest';

import { databaseUnavailable } from './apiErrors';

describe('databaseUnavailable', () => {
  afterEach(() => vi.restoreAllMocks());

  it('logs the internal cause but returns only a generic public message', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const response = databaseUnavailable(
      'labeler application',
      new Error('relation labeler_applications does not exist'),
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({
      detail: '서버 처리 중 오류가 발생했어. 잠시 후 다시 시도해.',
    });
    expect(consoleError).toHaveBeenCalledOnce();
  });
});
