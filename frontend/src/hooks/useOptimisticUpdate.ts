"use client";

import { useState, useCallback, useRef } from "react";

interface OptimisticState<T> {
  data: T;
  isLoading: boolean;
  error: Error | null;
}

type ToastFunction = (toast: { type: "success" | "error" | "warning" | "info"; title: string; message?: string }) => void;

interface UseOptimisticUpdateOptions<T> {
  initialData: T;
  onUpdate: (data: T) => Promise<void>;
  onError?: (error: Error, previousData: T) => void;
  rollbackOnError?: boolean;
  addToast?: ToastFunction;
}

export function useOptimisticUpdate<T>({
  initialData,
  onUpdate,
  onError,
  rollbackOnError = true,
  addToast,
}: UseOptimisticUpdateOptions<T>) {
  const [state, setState] = useState<OptimisticState<T>>({
    data: initialData,
    isLoading: false,
    error: null,
  });
  const previousDataRef = useRef<T>(initialData);

  const update = useCallback(
    async (newData: T) => {
      const previousData = previousDataRef.current;
      previousDataRef.current = newData;

      // Optimistically update immediately
      setState({
        data: newData,
        isLoading: true,
        error: null,
      });

      try {
        await onUpdate(newData);
        setState({
          data: newData,
          isLoading: false,
          error: null,
        });
      } catch (error) {
        const err = error instanceof Error ? error : new Error(String(error));

        if (rollbackOnError) {
          // Rollback to previous data
          setState({
            data: previousData,
            isLoading: false,
            error: err,
          });
          previousDataRef.current = previousData;
        } else {
          setState((prev) => ({
            ...prev,
            isLoading: false,
            error: err,
          }));
        }

        if (addToast) {
          addToast({
            type: "error",
            title: "Update Failed",
            message: err.message || "Failed to save changes",
          });
        }

        if (onError) {
          onError(err, previousData);
        }
      }
    },
    [onUpdate, onError, rollbackOnError, addToast]
  );

  const setData = useCallback((data: T) => {
    previousDataRef.current = data;
    setState((prev) => ({ ...prev, data }));
  }, []);

  return {
    data: state.data,
    isLoading: state.isLoading,
    error: state.error,
    update,
    setData,
  };
}

// Hook for managing a list with optimistic add/remove/update
export function useOptimisticList<T extends { id: string }>(
  initialItems: T[],
  addToast?: ToastFunction
) {
  const [items, setItems] = useState<T[]>(initialItems);

  const optimisticAdd = useCallback(
    async (item: T, addFn: () => Promise<void>) => {
      // Optimistically add
      setItems((prev) => [...prev, item]);

      try {
        await addFn();
        if (addToast) addToast({ type: "success", title: "Added successfully" });
      } catch (error) {
        // Rollback
        setItems((prev) => prev.filter((i) => i.id !== item.id));
        if (addToast) {
          addToast({
            type: "error",
            title: "Failed to add",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    },
    [addToast]
  );

  const optimisticRemove = useCallback(
    async (id: string, removeFn: () => Promise<void>) => {
      const item = items.find((i) => i.id === id);
      if (!item) return;

      // Optimistically remove
      setItems((prev) => prev.filter((i) => i.id !== id));

      try {
        await removeFn();
        if (addToast) addToast({ type: "success", title: "Deleted successfully" });
      } catch (error) {
        // Rollback
        setItems((prev) => [...prev, item]);
        if (addToast) {
          addToast({
            type: "error",
            title: "Failed to delete",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    },
    [items, addToast]
  );

  const optimisticUpdate = useCallback(
    async (id: string, updates: Partial<T>, updateFn: () => Promise<void>) => {
      const previousItems = items;
      const item = items.find((i) => i.id === id);
      if (!item) return;

      // Optimistically update
      setItems((prev) =>
        prev.map((i) => (i.id === id ? { ...i, ...updates } : i))
      );

      try {
        await updateFn();
        if (addToast) addToast({ type: "success", title: "Updated successfully" });
      } catch (error) {
        // Rollback
        setItems(previousItems);
        if (addToast) {
          addToast({
            type: "error",
            title: "Failed to update",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    },
    [items, addToast]
  );

  return {
    items,
    setItems,
    optimisticAdd,
    optimisticRemove,
    optimisticUpdate,
  };
}
