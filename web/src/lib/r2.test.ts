import { beforeEach, describe, expect, it, vi } from 'vitest';

const { getObjectCommandInput, getSignedUrl } = vi.hoisted(() => ({
  getObjectCommandInput: vi.fn(),
  getSignedUrl: vi.fn(),
}));

vi.mock('server-only', () => ({}));
vi.mock('@aws-sdk/client-s3', () => ({
  S3Client: class {},
  GetObjectCommand: class {
    constructor(input: unknown) {
      getObjectCommandInput(input);
    }
  },
  PutObjectCommand: class {},
  DeleteObjectCommand: class {},
}));
vi.mock('@aws-sdk/s3-request-presigner', () => ({ getSignedUrl }));

import { presignGet } from './r2';

describe('presignGet', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env.R2_ENDPOINT = 'https://r2.invalid';
    process.env.R2_ACCESS_KEY_ID = 'access';
    process.env.R2_SECRET_ACCESS_KEY = 'secret';
    process.env.R2_BUCKET = 'bucket';
    getSignedUrl.mockResolvedValue('https://signed.invalid/artifact');
  });

  it('gzip artifact의 원본 바이트를 받도록 response encoding을 identity로 서명한다', async () => {
    await presignGet(
      'terra-derived/gme/v1/permanent/artifact.json.gz',
      300,
      { responseContentEncoding: 'identity' },
    );

    expect(getObjectCommandInput).toHaveBeenCalledWith({
      Bucket: 'bucket',
      Key: 'terra-derived/gme/v1/permanent/artifact.json.gz',
      ResponseContentEncoding: 'identity',
    });
  });
});
