"use client";

import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useTheme } from "./ThemeProvider";

export type FontSize = "small" | "medium" | "large";
export type ReducedMotion = boolean;
export type CompactMode = boolean;

const STORAGE_KEY = "agent-collab.preferences";

export interface UserPreferences {
  fontSize: FontSize;
  reducedMotion: ReducedMotion;
  compactMode: CompactMode;
}

interface PreferencesContextValue extends UserPreferences {
  setFontSize: (size: FontSize) => void;
  setReducedMotion: (value: ReducedMotion) => void;
  setCompactMode: (value: CompactMode) => void;
}

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

const DEFAULT_PREFERENCES: UserPreferences = {
  fontSize: "medium",
  reducedMotion: false,
  compactMode: false,
};

function readStoredPreferences(): UserPreferences {
  if (typeof window === "undefined") return DEFAULT_PREFERENCES;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return { ...DEFAULT_PREFERENCES, ...JSON.parse(stored) };
    }
  } catch {}
  return DEFAULT_PREFERENCES;
}

function applyPreferences(prefs: UserPreferences) {
  document.documentElement.dataset.fontSize = prefs.fontSize;
  document.documentElement.dataset.compactMode = String(prefs.compactMode);
  document.documentElement.style.setProperty("--motion-reduced", prefs.reducedMotion ? "reduce" : "auto");
}

export function PreferencesProvider({ children }: { children: React.ReactNode }) {
  // Touch theme provider so prefs render lifecycle stays coupled with it.
  useTheme();
  // Same SSR-safe pattern as ThemeProvider — seed with defaults, hydrate
  // from localStorage in a useEffect after first commit. Prevents the
  // Settings page hydration mismatch when user previously toggled fontSize
  // or compactMode.
  const [prefs, setPrefs] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [hydrated, setHydrated] = useState(false);

  const setFontSize = (fontSize: FontSize) => setPrefs((p) => ({ ...p, fontSize }));
  const setReducedMotion = (reducedMotion: ReducedMotion) => setPrefs((p) => ({ ...p, reducedMotion }));
  const setCompactMode = (compactMode: CompactMode) => setPrefs((p) => ({ ...p, compactMode }));

  useEffect(() => {
    const stored = readStoredPreferences();
    setPrefs(stored);
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  }, [prefs, hydrated]);

  useEffect(() => {
    applyPreferences(prefs);
  }, [prefs]);

  const value = useMemo(
    () => ({ ...prefs, setFontSize, setReducedMotion, setCompactMode }),
    [prefs],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences() {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("usePreferences must be used inside PreferencesProvider");
  return value;
}