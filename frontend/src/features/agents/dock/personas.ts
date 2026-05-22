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
  /** i18n translation key for persona display name */
  nameKey: string;
  emoji: string;
  /** Accent color used for glow ring, bubble border, active tint. */
  color: string;
  /** i18n translation key for one-line role description shown in the timeline panel header. */
  blurbKey: string;
}

export const PERSONAS: Record<RoleId, Persona> = {
  conductor: {
    id: "conductor",
    nameKey: "dock.persona.conductor.name",
    emoji: "🎙️",
    color: "#a855f7",
    blurbKey: "dock.persona.conductor.blurb",
  },
  product_manager: {
    id: "product_manager",
    nameKey: "dock.persona.product_manager.name",
    emoji: "📊",
    color: "#3b82f6",
    blurbKey: "dock.persona.product_manager.blurb",
  },
  architect: {
    id: "architect",
    nameKey: "dock.persona.architect.name",
    emoji: "🏗️",
    color: "#22c55e",
    blurbKey: "dock.persona.architect.blurb",
  },
  engineer: {
    id: "engineer",
    nameKey: "dock.persona.engineer.name",
    emoji: "⚙️",
    color: "#f59e0b",
    blurbKey: "dock.persona.engineer.blurb",
  },
  engineer_frontend: {
    id: "engineer_frontend",
    nameKey: "dock.persona.engineer_frontend.name",
    emoji: "🎨",
    color: "#06b6d4",
    blurbKey: "dock.persona.engineer_frontend.blurb",
  },
  engineer_backend: {
    id: "engineer_backend",
    nameKey: "dock.persona.engineer_backend.name",
    emoji: "🔧",
    color: "#a855f7",
    blurbKey: "dock.persona.engineer_backend.blurb",
  },
  qa: {
    id: "qa",
    nameKey: "dock.persona.qa.name",
    emoji: "🔎",
    color: "#ef4444",
    blurbKey: "dock.persona.qa.blurb",
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
