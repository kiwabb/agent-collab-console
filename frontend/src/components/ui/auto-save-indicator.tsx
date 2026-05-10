"use client"

import { useEffect, useState } from "react"
import { Check, AlertCircle, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
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
      className={cn(
        "flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest transition-all duration-300",
        status === "saving" && "text-text-muted",
        status === "saved" && "text-success",
        status === "error" && "text-error",
        visible ? "opacity-100" : "opacity-0",
        className
      )}
    >
      {status === "saving" && (
        <>
          <Loader2 size={12} className="animate-spin" />
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