"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { CodexIssue } from "@/lib/types";
import { IssueCard } from "./IssueCard";
import { GripVertical } from "lucide-react";

interface SortableIssueCardProps {
  issue: CodexIssue;
  isSelected: boolean;
  taskCount: number;
  runningCount: number;
  failedCount: number;
  waitingCount: number;
  onClick: () => void;
  onUpdateIssue?:
    ((id: string, updates: { title?: string; description?: string }) => void) | undefined;
  onPinIssue?: ((id: string, isPinned: boolean) => void) | undefined;
  onDuplicateIssue?: ((id: string) => void) | undefined;
}

export function SortableIssueCard({
  issue,
  isSelected,
  taskCount,
  runningCount,
  failedCount,
  waitingCount,
  onClick,
  onUpdateIssue,
  onPinIssue,
  onDuplicateIssue,
}: SortableIssueCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: issue.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 1000 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} className="relative group/sortable">
      <div
        {...attributes}
        {...listeners}
        className="absolute left-2 top-1/2 -translate-y-1/2 opacity-0 group-hover/sortable:opacity-100 transition-opacity cursor-grab active:cursor-grabbing p-1 rounded hover:bg-surface-hover"
      >
        <GripVertical size={14} className="text-text-muted" />
      </div>
      <div className="pl-6">
        <IssueCard
          issue={issue}
          isSelected={isSelected}
          taskCount={taskCount}
          runningCount={runningCount}
          failedCount={failedCount}
          waitingCount={waitingCount}
          onClick={onClick}
          onUpdateIssue={onUpdateIssue}
          onPinIssue={onPinIssue}
          onDuplicateIssue={onDuplicateIssue}
        />
      </div>
    </div>
  );
}
