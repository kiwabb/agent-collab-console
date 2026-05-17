"use client";

/**
 * Cross-component data-change bus.
 *
 * When one part of the UI mutates a domain entity (workspace, issue, …),
 * other parts that have already loaded a list of those entities need a
 * signal to refetch. This is a tiny pub-sub for that — no provider needed,
 * works across route boundaries because subscribers register against a
 * module-level Map.
 *
 * Usage:
 *
 *   // Mutator side:
 *   await deleteWorkspace(id);
 *   emitDataEvent("workspaces:changed");
 *
 *   // Subscriber side:
 *   useDataEvent("workspaces:changed", () => void refetch());
 */

import { useEffect } from "react";

export type DataEventName =
  | "workspaces:changed"
  | "issues:changed"
  | "projects:changed";

type Handler = () => void;

const subscribers = new Map<DataEventName, Set<Handler>>();

export function emitDataEvent(name: DataEventName): void {
  const set = subscribers.get(name);
  if (!set) return;
  for (const fn of set) {
    try {
      fn();
    } catch (err) {
      // Swallow handler errors so one bad subscriber doesn't poison the rest.
      console.error(`[dataEvents] handler for ${name} threw`, err);
    }
  }
}

export function useDataEvent(name: DataEventName, handler: Handler): void {
  useEffect(() => {
    let set = subscribers.get(name);
    if (!set) {
      set = new Set();
      subscribers.set(name, set);
    }
    set.add(handler);
    return () => {
      set?.delete(handler);
    };
  }, [name, handler]);
}
