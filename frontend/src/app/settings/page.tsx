"use client";

import { SettingsPage } from "@/features/settings/SettingsPage";
import { WorkbenchShell } from "@/features/workbench/WorkbenchShell";
import { useI18n } from "@/providers/I18nProvider";

export default function Page() {
  const { t } = useI18n();
  return (
    <WorkbenchShell breadcrumbs={[{ label: t("settings.title") }]}>
      <SettingsPage />
    </WorkbenchShell>
  );
}
