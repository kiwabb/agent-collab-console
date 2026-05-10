import type { Metadata } from "next";
import "@/app/globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { I18nProvider } from "@/providers/I18nProvider";
import { PreferencesProvider } from "@/providers/PreferencesProvider";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { OnboardingTourProvider } from "@/components/onboarding/OnboardingTooltip";
import { OnboardingGuide } from "@/components/onboarding/OnboardingGuide";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

export const metadata: Metadata = {
  title: "Agent Collaboration Workbench",
  description: "Jira-like agent collaboration and coordination platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className={cn("font-sans", geist.variable)} suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => {
              try {
                const stored = localStorage.getItem("agent-collab.theme") || "system";
                const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
                const theme = stored === "dark" || (stored === "system" && systemDark) ? "dark" : "light";
                document.documentElement.dataset.theme = theme;
                document.documentElement.classList.toggle("dark", theme === "dark");
                document.documentElement.style.colorScheme = theme;
                const prefs = JSON.parse(localStorage.getItem("agent-collab.preferences") || "{}");
                if (prefs.fontSize) document.documentElement.dataset.fontSize = prefs.fontSize;
                if (prefs.compactMode) document.documentElement.dataset.compactMode = String(prefs.compactMode);
              } catch {}
            })();`,
          }}
        />
      </head>
      <body><OnboardingTourProvider><ThemeProvider><PreferencesProvider><I18nProvider><TooltipProvider delay={200}><ToastProvider>{children}<OnboardingGuide /></ToastProvider></TooltipProvider></I18nProvider></PreferencesProvider></ThemeProvider></OnboardingTourProvider></body>
    </html>
  );
}
