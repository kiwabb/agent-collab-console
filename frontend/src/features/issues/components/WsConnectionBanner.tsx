"use client";

import { WifiOff } from "lucide-react";

import { useWsConnectionStatus } from "../hooks/useWsConnectionStatus";

export function WsConnectionBanner() {
  const { showDisconnected, recoveredCount } = useWsConnectionStatus();
  if (recoveredCount != null) {
    return (
      <div className="rounded-2xl border border-status-done/30 bg-status-done/10 px-4 py-2 text-sm font-semibold text-status-done">
        ✓ 已补齐 {recoveredCount} 个事件
      </div>
    );
  }
  if (!showDisconnected) return null;
  return (
    <div className="rounded-2xl border border-status-info/30 bg-status-info/10 px-4 py-2 text-sm font-semibold text-status-info">
      <span className="inline-flex items-center gap-2">
        <WifiOff size={15} /> 实时连接丢失，重连中...
      </span>
    </div>
  );
}
