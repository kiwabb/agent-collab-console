"use client";

import { useState, useCallback, useRef } from "react";

interface UndoEntry<T> {
  past: T[];
  present: T;
  future: T[];
}

export function useUndoRedo<T>(initialPresent: T, maxHistory = 50) {
  const [state, setState] = useState<UndoEntry<T>>({
    past: [],
    present: initialPresent,
    future: [],
  });

  const initialPresentRef = useRef(initialPresent);

  const canUndo = state.past.length > 0;
  const canRedo = state.future.length > 0;

  const set = useCallback(
    (newPresent: T, addToHistory = true) => {
      setState((current) => {
        if (!addToHistory) {
          return { ...current, present: newPresent };
        }
        return {
          past: [...current.past, current.present].slice(-maxHistory),
          present: newPresent,
          future: [],
        };
      });
    },
    [maxHistory],
  );

  const undo = useCallback(() => {
    setState((current) => {
      if (current.past.length === 0) return current;
      const newPast = [...current.past];
      const newPresent = newPast.pop()!;
      return {
        past: newPast,
        present: newPresent,
        future: [current.present, ...current.future],
      };
    });
  }, []);

  const redo = useCallback(() => {
    setState((current) => {
      if (current.future.length === 0) return current;
      const newFuture = [...current.future];
      const newPresent = newFuture.shift()!;
      return {
        past: [...current.past, current.present],
        present: newPresent,
        future: newFuture,
      };
    });
  }, []);

  const reset = useCallback((newPresent?: T) => {
    setState({
      past: [],
      present: newPresent ?? initialPresentRef.current,
      future: [],
    });
  }, []);

  return {
    past: state.past,
    present: state.present,
    future: state.future,
    canUndo,
    canRedo,
    set,
    undo,
    redo,
    reset,
  };
}

export function useUndoRedoSimple<T>(
  getValue: () => T,
  setValue: (value: T) => void,
  maxHistory = 50,
) {
  const historyRef = useRef<T[]>([]);
  const futureRef = useRef<T[]>([]);
  const isUndoRedoRef = useRef(false);

  const pushHistory = useCallback(
    (value: T) => {
      if (isUndoRedoRef.current) return;
      historyRef.current.push(value);
      if (historyRef.current.length > maxHistory) {
        historyRef.current.shift();
      }
      futureRef.current = [];
    },
    [maxHistory],
  );

  const undo = useCallback(() => {
    if (historyRef.current.length === 0) return;
    const previous = historyRef.current.pop()!;
    futureRef.current.unshift(getValue());
    isUndoRedoRef.current = true;
    setValue(previous);
    isUndoRedoRef.current = false;
  }, [getValue, setValue]);

  const redo = useCallback(() => {
    if (futureRef.current.length === 0) return;
    const next = futureRef.current.shift()!;
    historyRef.current.push(getValue());
    isUndoRedoRef.current = true;
    setValue(next);
    isUndoRedoRef.current = false;
  }, [getValue, setValue]);

  return {
    pushHistory,
    undo,
    redo,
    canUndo: () => historyRef.current.length > 0,
    canRedo: () => futureRef.current.length > 0,
  };
}
