"use client"

import { useEffect, useState } from "react"
import { Check, AlertCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator"
import { useI18n } from "@/providers/I18nProvider"

type SaveStatus = "idle" | "saving" | "saved" | "error"

interface AutoSaveIndicatorProps {
  status: SaveStatus
  error?: string | null
  className?: string
}

export function AutoSaveIndicator({ status, error, className }: AutoSaveIndicatorProps) {
  const { t } = useI18n()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (status === "saving") {
      setVisible(true)
    } else if (status === "saved") {
      setVisible(true)
      const timer = setTimeout(() => setVisible(false), 2000)
      return () => clearTimeout(timer)
    } else if (status === "error") {
      setVisible(true)
    }
  }, [status])

  if (!visible && status === "idle") return null

  return (
    <div
      data-density={status === "saving" ? "auto-save-indicator-tool" : "auto-save-indicator"}
      className={cn(
        "flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest transition-all duration-300",
        status === "saving" && "motion-essential text-text-muted",
        status === "saved" && "text-success",
        status === "error" && "text-error",
        visible ? "opacity-100" : "opacity-0",
        className
      )}
    >
      {status === "saving" && (
        <>
          <AgentThinkingIndicator phase="tool" size={12} />
          <span>{t("autosave.saving")}</span>
        </>
      )}
      {status === "saved" && (
        <>
          <Check size={12} />
          <span>{t("autosave.saved")}</span>
        </>
      )}
      {status === "error" && (
        <>
          <AlertCircle size={12} />
          <span>{error || t("autosave.error")}</span>
        </>
      )}
    </div>
  )
}