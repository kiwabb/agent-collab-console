"use client";

import { WifiOff } from "lucide-react";

import { useI18n } from "@/providers/I18nProvider";
import { useWsConnectionStatus } from "../hooks/useWsConnectionStatus";

export function WsConnectionBanner() {
  const { t } = useI18n();
  const { showDisconnected, recoveredCount } = useWsConnectionStatus();
  if (recoveredCount != null) {
    return (
      <div className="rounded-2xl border border-status-done/30 bg-status-done/10 px-4 py-2 text-sm font-semibold text-status-done">
        ✓ {t("issue.command.wsRecovered", { count: recoveredCount })}
      </div>
    );
  }
  if (!showDisconnected) return null;
  return (
    <div className="rounded-2xl border border-status-info/30 bg-status-info/10 px-4 py-2 text-sm font-semibold text-status-info">
      <span className="inline-flex items-center gap-2">
        <WifiOff size={15} /> {t("issue.command.wsDisconnected")}
      </span>
    </div>
  );
}
