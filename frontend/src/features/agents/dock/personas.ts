/**
 * Persona table for the bottom Agent Dock.
 *
 * Each entry binds a logical agent role to a placeholder visual identity
 * (emoji + accent color + display name). Real character illustrations or
 * Lottie animations will swap in here later — every consumer of the dock
 * reads from this table, so changing a face is a one-file edit.
 *
 * `conductor` is the Workflow Orchestrator persona (Auto-plan LLM +
 * scheduler). It has no backing `Agent` row in the DB — it represents the
 * framework itself driving the other four.
 */

export type RoleId =
  | "conductor"
  | "product_manager"
  | "architect"
  | "engineer"
  // Phase 1 — specialist engineers that run in parallel after Architect
  // when an issue spans both frontend and backend work.
  | "engineer_frontend"
  | "engineer_backend"
  | "qa";

export interface Persona {
  id: RoleId;
  name: string;
  emoji: string;
  /** Accent color used for glow ring, bubble border, active tint. */
  color: string;
  /** One-line role description shown in the timeline panel header. */
  blurb: string;
}

export const PERSONAS: Record<RoleId, Persona> = {
  conductor: {
    id: "conductor",
    name: "Conductor",
    emoji: "🎙️",
    color: "#a855f7",
    blurb: "Plans the DAG and routes work between the other four.",
  },
  product_manager: {
    id: "product_manager",
    name: "PM",
    emoji: "📊",
    color: "#3b82f6",
    blurb: "Reads the issue, drafts the PRD.",
  },
  architect: {
    id: "architect",
    name: "Architect",
    emoji: "🏗️",
    color: "#22c55e",
    blurb: "Designs the system and breaks the implementation into tasks.",
  },
  engineer: {
    id: "engineer",
    name: "Engineer",
    emoji: "⚙️",
    color: "#f59e0b",
    blurb: "Writes the code, runs the tests.",
  },
  engineer_frontend: {
    id: "engineer_frontend",
    name: "FE Engineer",
    emoji: "🎨",
    color: "#06b6d4",
    blurb: "Implements the UI / client slice.",
  },
  engineer_backend: {
    id: "engineer_backend",
    name: "BE Engineer",
    emoji: "🔧",
    color: "#a855f7",
    blurb: "Implements the API / server slice.",
  },
  qa: {
    id: "qa",
    name: "QA",
    emoji: "🔎",
    color: "#ef4444",
    blurb: "Validates the implementation, files follow-ups.",
  },
};

/** Canonical order shown in the dock, left → right. */
export const ROLE_ORDER: RoleId[] = [
  "conductor",
  "product_manager",
  "architect",
  "engineer",
  "qa",
];
