import { createPostFromEnv } from '@/lib/yoloDemoRoute';

export const runtime = 'nodejs';

export const POST = createPostFromEnv(process.env);
