"use client";

import { useEffect, useState } from "react";
import { getCodexIssueArtifacts } from "@/lib/api";
import type { Artifact } from "@/lib/types";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";

interface Props {
  issueId: string;
}

export function ArtifactsTab({ issueId }: Props) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    setIsLoading(true);
    getCodexIssueArtifacts(issueId)
      .then(setArtifacts)
      .catch(() => setArtifacts([]))
      .finally(() => setIsLoading(false));
  }, [issueId]);

  return (
    <div className="p-6 h-full">
      <ArtifactPanel artifacts={artifacts} isLoading={isLoading} />
    </div>
  );
}
