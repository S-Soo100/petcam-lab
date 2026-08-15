import { requireOwner } from '@/lib/labelingAccess';
import { createOwnerPreviewPost } from '@/lib/yoloOwnerPreviewRoute';

export const runtime = 'nodejs';

export const POST = createOwnerPreviewPost({
  env: process.env,
  requireOwner,
});
