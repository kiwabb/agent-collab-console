"use client";

import { CollabFeedTab } from "../tabs/CollabFeedTab";

export function MeshPanel({ issueId }: { issueId: string }) {
  return (
    <div className="h-full min-h-0 flex flex-col">
      <CollabFeedTab issueId={issueId} active />
    </div>
  );
}
