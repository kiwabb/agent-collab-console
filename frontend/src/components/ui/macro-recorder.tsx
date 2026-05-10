"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  Keyboard,
  Record,
  Square,
  Play,
  Trash2,
  Plus,
  GripVertical,
  MoreHorizontal,
  X,
} from "lucide-react";

interface MacroAction {
  type: "click" | "key" | "type";
  target?: string;
  value?: string;
  key?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

interface Macro {
  id: string;
  name: string;
  actions: MacroAction[];
  createdAt: number;
}

interface MacroRecorderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUseMacro?: (macro: Macro) => void;
}

export function useMacros() {
  const [macros, setMacros] = useState<Macro[]>([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("agent-collab.macros");
      if (stored) setMacros(JSON.parse(stored));
    } catch {}
  }, []);

  const saveMacros = useCallback((updated: Macro[]) => {
    setMacros(updated);
    localStorage.setItem("agent-collab.macros", JSON.stringify(updated));
  }, []);

  const createMacro = useCallback((name: string, actions: MacroAction[]) => {
    const macro: Macro = {
      id: `macro-${Date.now()}`,
      name,
      actions,
      createdAt: Date.now(),
    };
    setMacros((prev) => {
      const next = [macro, ...prev].slice(0, 20);
      localStorage.setItem("agent-collab.macros", JSON.stringify(next));
      return next;
    });
    return macro;
  }, []);

  const deleteMacro = useCallback((id: string) => {
    setMacros((prev) => {
      const next = prev.filter((m) => m.id !== id);
      localStorage.setItem("agent-collab.macros", JSON.stringify(next));
      return next;
    });
  }, []);

  const updateMacro = useCallback((id: string, updates: Partial<Macro>) => {
    setMacros((prev) => {
      const next = prev.map((m) => (m.id === id ? { ...m, ...updates } : m));
      localStorage.setItem("agent-collab.macros", JSON.stringify(next));
      return next;
    });
  }, []);

  const runMacro = useCallback((macro: Macro) => {
    for (const action of macro.actions) {
      if (action.type === "click" && action.target) {
        const el = document.querySelector(action.target);
        if (el instanceof HTMLElement) el.click();
      } else if (action.type === "key") {
        const event = new KeyboardEvent("keydown", {
          key: action.key,
          ctrlKey: action.ctrlKey,
          metaKey: action.metaKey,
          shiftKey: action.shiftKey,
          altKey: action.altKey,
          bubbles: true,
        });
        document.dispatchEvent(event);
      }
    }
  }, []);

  return { macros, createMacro, deleteMacro, updateMacro, runMacro };
}

export function MacroRecorder({ open, onOpenChange, onUseMacro }: MacroRecorderProps) {
  const [recording, setRecording] = useState(false);
  const [actions, setActions] = useState<MacroAction[]>([]);
  const [name, setName] = useState("");
  const [activeTab, setActiveTab] = useState<"record" | "library">("record");
  const { macros, createMacro, deleteMacro, runMacro } = useMacros();
  const keyRef = useRef<{ key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean } | null>(null);

  const startRecording = useCallback(() => {
    setRecording(true);
    setActions([]);
    setName("");
  }, []);

  const stopRecording = useCallback(() => {
    setRecording(false);
  }, []);

  useEffect(() => {
    if (!recording) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      keyRef.current = {
        key: e.key,
        ctrlKey: e.ctrlKey,
        metaKey: e.metaKey,
        shiftKey: e.shiftKey,
        altKey: e.altKey,
      };
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (!keyRef.current || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      setActions((prev) => [
        ...prev,
        {
          type: "key",
          key: keyRef.current!.key,
          ctrlKey: keyRef.current!.ctrlKey,
          metaKey: keyRef.current!.metaKey,
          shiftKey: keyRef.current!.shiftKey,
          altKey: keyRef.current!.altKey,
        },
      ]);
      keyRef.current = null;
    };

    const handleClick = (e: MouseEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const target = e.target as HTMLElement;
      if (target.closest("[data-command-palette]")) return;
      const selector = getSelector(target);
      if (selector) {
        setActions((prev) => [...prev, { type: "click", target: selector }]);
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("keyup", handleKeyUp);
    document.addEventListener("click", handleClick, true);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("keyup", handleKeyUp);
      document.removeEventListener("click", handleClick, true);
    };
  }, [recording]);

  const handleSave = () => {
    if (!name.trim() || actions.length === 0) return;
    createMacro(name.trim(), actions);
    setActions([]);
    setName("");
    setActiveTab("library");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg gap-0 p-0 overflow-hidden">
        <DialogHeader className="px-6 py-4 border-b border-border-subtle bg-surface/50">
          <DialogTitle className="flex items-center gap-2 text-base">
            <Keyboard size={18} />
            Keyboard Macros
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-1 px-4 py-2 border-b border-border-subtle bg-surface/30">
          {(["record", "library"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[10px] font-black uppercase tracking-widest transition-all",
                activeTab === t ? "bg-brand/10 text-brand" : "text-text-muted hover:text-foreground"
              )}
            >
              {t === "record" ? <Record size={12} /> : <Keyboard size={12} />}
              {t}
            </button>
          ))}
        </div>

        <div className="max-h-[400px] overflow-y-auto p-4">
          {activeTab === "record" && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                {recording ? (
                  <Button variant="destructive" size="sm" onClick={stopRecording}>
                    <Square size={14} className="mr-1" /> Stop
                  </Button>
                ) : (
                  <Button size="sm" onClick={startRecording}>
                    <Record size={14} className="mr-1" /> Start Recording
                  </Button>
                )}
                {recording && (
                  <div className="flex items-center gap-2 text-xs text-text-muted">
                    <div className="size-2 rounded-full bg-error animate-pulse" />
                    Recording action
                    <Kbd className="text-[10px]">ESC</Kbd> to stop
                  </div>
                )}
              </div>

              {actions.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] uppercase tracking-widest font-bold text-text-muted">
                    Recorded ({actions.length})
                  </p>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {actions.map((action, i) => (
                      <div key={i} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-raised text-xs">
                        <span className="text-text-muted font-mono">{i + 1}.</span>
                        {action.type === "click" && (
                          <>
                            <span className="text-brand">Click</span>
                            <code className="text-[10px] text-text-muted font-mono bg-surface px-1 rounded">
                              {action.target}
                            </code>
                          </>
                        )}
                        {action.type === "key" && (
                          <span className="text-brand">Key:</span>
                        )}
                        {action.type === "key" && action.key && (
                          <div className="flex items-center gap-0.5">
                            {action.ctrlKey && <Kbd className="text-[10px]">Ctrl</Kbd>}
                            {action.metaKey && <Kbd className="text-[10px]">⌘</Kbd>}
                            {action.shiftKey && <Kbd className="text-[10px]">⇧</Kbd>}
                            {action.altKey && <Kbd className="text-[10px]">⌥</Kbd>}
                            <Kbd className="text-[10px]">{action.key}</Kbd>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {actions.length > 0 && (
                <div className="flex items-center gap-2 pt-2">
                  <Input
                    placeholder="Macro name..."
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="h-8 text-sm"
                  />
                  <Button size="sm" onClick={handleSave} disabled={!name.trim()}>
                    Save
                  </Button>
                </div>
              )}
            </div>
          )}

          {activeTab === "library" && (
            <div className="space-y-2">
              {macros.length === 0 && (
                <p className="text-xs text-text-muted text-center py-8">
                  No macros yet. Record some to get started.
                </p>
              )}
              {macros.map((macro) => (
                <div
                  key={macro.id}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-surface-raised border border-border-subtle group"
                >
                  <div className="size-8 rounded-lg bg-brand/10 flex items-center justify-center text-brand">
                    <Keyboard size={14} />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-bold text-foreground">{macro.name}</p>
                    <p className="text-[10px] text-text-muted">{macro.actions.length} actions</p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => { runMacro(macro); onOpenChange(false); }}
                    >
                      <Play size={14} />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => deleteMacro(macro.id)}
                    >
                      <Trash2 size={14} className="text-error" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function getSelector(el: HTMLElement): string | null {
  if (el.id) return `#${el.id}`;
  if (el.className && typeof el.className === "string") {
    const classes = el.className.split(" ").filter(Boolean).slice(0, 2).join(".");
    if (classes) return `.${classes}`;
  }
  return el.tagName.toLowerCase();
}