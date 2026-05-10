import type { Metadata } from "next";
import "@/app/globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { I18nProvider } from "@/providers/I18nProvider";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";

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
              } catch {}
            })();`,
          }}
        />
      </head>
      <body><ThemeProvider><I18nProvider><TooltipProvider delay={200}><ToastProvider>{children}</ToastProvider></TooltipProvider></I18nProvider></ThemeProvider></body>
    </html>
  );
}
