"use client";

import { CollabFeedTab } from "../tabs/CollabFeedTab";

export function MeshPanel({ issueId }: { issueId: string }) {
  return (
    <div className="h-[520px]">
      <CollabFeedTab issueId={issueId} active />
    </div>
  );
}
