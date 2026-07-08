"use client";

import { AlertOctagon, AlertTriangle, Info, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import type { ConductorAlert } from "../hooks/useConductorAlerts";

interface Props {
  alerts: ConductorAlert[];
  onDismiss: (id: string) => void;
}

const SEVERITY_STYLE: Record<ConductorAlert["severity"], string> = {
  danger: "border-status-failed/35 bg-status-failed/10 text-status-failed",
  warn: "border-status-awaiting/40 bg-status-awaiting/10 text-status-awaiting",
  info: "border-border-subtle bg-surface-raised/70 text-text-secondary",
};

const SEVERITY_ICON = {
  danger: AlertOctagon,
  warn: AlertTriangle,
  info: Info,
} as const;

export function ConductorAlerts({ alerts, onDismiss }: Props) {
  const { t } = useI18n();
  if (alerts.length === 0) return null;

  return (
    <section className="flex flex-col gap-2" data-conductor-alerts>
      {alerts.map((alert) => {
        const Icon = SEVERITY_ICON[alert.severity];
        const isOperationalConductorAlert = alert.severity !== "info";
        return (
          <div
            key={alert.id}
            data-density={
              isOperationalConductorAlert ? "conductor-alert-operational" : "conductor-alert-info"
            }
            className={cn(
              "relative flex items-center justify-between gap-3 overflow-hidden rounded-2xl border px-4 py-2.5",
              SEVERITY_STYLE[alert.severity],
              isOperationalConductorAlert && "motion-essential",
            )}
          >
            {isOperationalConductorAlert && (
              <div
                aria-hidden
                className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-current/60 to-transparent"
              />
            )}
            <div className="flex min-w-0 items-center gap-2">
              <Icon size={15} className="shrink-0" />
              <p className="truncate text-sm font-semibold">{t(alert.titleKey, alert.params)}</p>
            </div>
            <button
              type="button"
              onClick={() => onDismiss(alert.id)}
              aria-label={t("issue.command.alert.dismiss")}
              className="shrink-0 rounded-lg p-1 text-current/70 transition hover:bg-current/10 hover:text-current"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </section>
  );
}
