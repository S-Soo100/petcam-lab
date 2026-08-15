import { ownerPreviewWorkerConfig } from '@/lib/yoloOwnerPreviewRoute';
import { OwnerYoloPageClient } from './_owner-yolo-page-client';

export default function OwnerYoloPage() {
  return <OwnerYoloPageClient previewEnabled={ownerPreviewWorkerConfig(process.env) !== null} />;
}
