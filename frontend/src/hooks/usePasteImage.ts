"use client";

import { useEffect, useCallback } from "react";

interface UsePasteImageOptions {
  onPaste: (file: File) => void;
  enabled?: boolean;
}

export function usePasteImage({ onPaste, enabled = true }: UsePasteImageOptions) {
  const handlePaste = useCallback(
    (event: ClipboardEvent) => {
      if (!enabled) return;

      const items = event.clipboardData?.items;
      if (!items) return;

      for (const item of items) {
        if (item.type.startsWith("image/")) {
          event.preventDefault();
          const file = item.getAsFile();
          if (file) {
            onPaste(file);
          }
          return;
        }
      }
    },
    [onPaste, enabled],
  );

  useEffect(() => {
    if (!enabled) return;
    window.addEventListener("paste", handlePaste);
    return () => window.removeEventListener("paste", handlePaste);
  }, [handlePaste, enabled]);
}

export function dataUrlToBlob(dataUrl: string): Blob {
  const [metadata = "", encodedData = ""] = dataUrl.split(",");
  const mime = metadata.match(/:(.*?);/)?.[1] || "image/png";
  const bstr = atob(encodedData);
  let n = bstr.length;
  const u8arr = new Uint8Array(n);
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n);
  }
  return new Blob([u8arr], { type: mime });
}
