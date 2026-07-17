import { useEffect } from "react";

type KeyboardShortcut = {
  key: string;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
  action: () => void;
  description?: string;
};

function matchesKey(event: KeyboardEvent, shortcut: KeyboardShortcut): boolean {
  const key = shortcut.key.length === 1 ? shortcut.key.toLowerCase() : shortcut.key;
  const pressedKey = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (pressedKey !== key) {
    return false;
  }
  if (shortcut.ctrlKey === true && !event.ctrlKey) return false;
  if (shortcut.shiftKey === true && !event.shiftKey) return false;
  if (shortcut.altKey === true && !event.altKey) return false;
  if (shortcut.metaKey === true && !event.metaKey) return false;
  if (shortcut.ctrlKey === false && event.ctrlKey) return false;
  if (shortcut.shiftKey === false && event.shiftKey) return false;
  if (shortcut.altKey === false && event.altKey) return false;
  if (shortcut.metaKey === false && event.metaKey) return false;
  return true;
}

export function isKeyboardShortcutEditableTarget(target: EventTarget | null): boolean {
  return (
    typeof Element !== "undefined" &&
    target instanceof Element &&
    target.closest("input, textarea, select, [contenteditable]") !== null
  );
}

export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]): void {
  useEffect(() => {
    if (typeof document === "undefined") return;

    const handler = (event: KeyboardEvent): void => {
      if (!shortcuts || shortcuts.length === 0) return;
      if (isKeyboardShortcutEditableTarget(event.target)) return;
      for (const shortcut of shortcuts) {
        if (matchesKey(event, shortcut)) {
          event.preventDefault();
          shortcut.action();
          return;
        }
      }
    };

    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [shortcuts]);
}
