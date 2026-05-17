"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useAgentStatus, type AgentStatusSnapshot } from "./useAgentStatus";
import { type RoleId } from "./personas";

/**
 * Single shared snapshot of the agent status across the issue page, so:
 *   - The 3s graph poll + message stream subscriptions in `useAgentStatus`
 *     run exactly once (not once per character tile).
 *   - `AgentDagNode` instances can read the slice they need.
 */
const AgentStatusContext = createContext<AgentStatusSnapshot | null>(null);

interface Props {
  issueId: string;
  children: ReactNode;
}

export function AgentStatusProvider({ issueId, children }: Props) {
  const snapshot = useAgentStatus(issueId);
  return (
    <AgentStatusContext.Provider value={snapshot}>
      {children}
    </AgentStatusContext.Provider>
  );
}

export function useAgentStatusContext(): AgentStatusSnapshot {
  const ctx = useContext(AgentStatusContext);
  if (ctx) return ctx;
  // Fall back to a zero state when used outside a provider so the canvas
  // renders even on the AgentLibraryPage or other reuse points.
  return {
    byRole: {
      conductor: { role: "conductor", text: "", mode: "idle", tone: "neutral" },
      product_manager: { role: "product_manager", text: "", mode: "idle", tone: "neutral" },
      architect: { role: "architect", text: "", mode: "idle", tone: "neutral" },
      engineer: { role: "engineer", text: "", mode: "idle", tone: "neutral" },
      qa: { role: "qa", text: "", mode: "idle", tone: "neutral" },
    },
    activeRole: null,
    history: {
      conductor: [],
      product_manager: [],
      architect: [],
      engineer: [],
      qa: [],
    },
  };
}

export function useRoleStatus(role: RoleId) {
  const snap = useAgentStatusContext();
  return {
    status: snap.byRole[role],
    isActive: snap.activeRole === role,
  };
}
