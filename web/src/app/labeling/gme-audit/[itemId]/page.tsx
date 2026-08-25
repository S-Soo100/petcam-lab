import GmeAuditWorkspace from '../_gme-audit-workspace';

export default function GmeAuditItemPage({ params }: { params: { itemId: string } }) {
  return <GmeAuditWorkspace itemId={params.itemId} />;
}
