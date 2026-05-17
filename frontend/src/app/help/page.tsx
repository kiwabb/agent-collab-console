"use client";

import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { HelpPage } from "@/features/help/HelpPage";
import { useI18n } from "@/providers/I18nProvider";

export default function Page() {
  const { t } = useI18n();
  return (
    <WorkbenchShell breadcrumbs={[{ label: t("shortcuts.help") }]}>
      <HelpPage />
    </WorkbenchShell>
  );
}
