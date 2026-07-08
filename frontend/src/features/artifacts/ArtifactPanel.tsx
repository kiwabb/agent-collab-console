"use client";

import type { Artifact } from "@/lib/types";
import { VirtualizedArtifactList } from "@/components/ui/virtualized-artifact-list";

interface ArtifactPanelProps {
  artifacts: Artifact[];
  isLoading?: boolean;
}

export function ArtifactPanel({ artifacts, isLoading }: ArtifactPanelProps) {
  return <VirtualizedArtifactList artifacts={artifacts} isLoading={isLoading} />;
}
