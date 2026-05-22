"use client";

import { useRouter } from "next/navigation";
import {
  CheckCircle2,
  GitBranch,
  GitFork,
  GitPullRequest,
  HelpCircle,
  Inbox,
  KeyRound,
  Layers,
  MessageSquarePlus,
  Play,
  ShieldCheck,
  Sparkles,
  Terminal,
  Undo2,
  Users,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/providers/I18nProvider";
import { PageFrame } from "@/features/workbench/components/PageFrame";

/**
 * One-stop "how do I use this thing" page.
 *
 * Three sections:
 *   1. Quick start in N steps (copy-paste-able, with deep links)
 *   2. Map of every page + what it's for
 *   3. Keyboard shortcuts
 *
 * Linked from the header `?` icon and the sidebar "Shortcuts" entry.
 */
export function HelpPage() {
  const { t } = useI18n();
  const router = useRouter();

  return (
    <PageFrame
      eyebrow={t("help.gettingStarted")}
      title={t("help.gettingStarted")}
      description={t("help.gettingStartedDesc")}
      maxWidthClassName="max-w-[1080px]"
      contentClassName="space-y-12"
      actions={(
        <Button
          onClick={() => router.push("/")}
          className="bg-brand hover:bg-brand-strong text-black font-semibold"
        >
          {t("help.backToInbox")}
        </Button>
      )}
    >
        {/* Quick start */}
        <section>
          <h2 className="text-xs font-black uppercase tracking-widest text-text-muted mb-4">
            {t("help.quickStart")}
          </h2>
          <ol className="space-y-3">
            <Step
              n={1}
              icon={<Layers size={14} />}
              title={t("help.step1.title")}
              body={<span dangerouslySetInnerHTML={{ __html: t("help.step1.body") }} />}
              cta={{ label: t("help.step1.cta"), onClick: () => router.push("/projects") }}
            />
            <Step
              n={2}
              icon={<Inbox size={14} />}
              title={t("help.step2.title")}
              body={<span dangerouslySetInnerHTML={{ __html: t("help.step2.body") }} />}
            />
            <Step
              n={3}
              icon={<Sparkles size={14} />}
              title={t("help.step3.title")}
              body={<span dangerouslySetInnerHTML={{ __html: t("help.step3.body") }} />}
            />
            <Step
              n={4}
              icon={<Play size={14} />}
              title={t("help.step4.title")}
              body={<span dangerouslySetInnerHTML={{ __html: t("help.step4.body") }} />}
            />
            <Step
              n={5}
              icon={<GitPullRequest size={14} />}
              title={t("help.step5.title")}
              body={<span dangerouslySetInnerHTML={{ __html: t("help.step5.body") }} />}
            />
          </ol>
        </section>

        {/* Page map */}
        <section>
          <h2 className="text-xs font-black uppercase tracking-widest text-text-muted mb-4">
            {t("help.pageMap")}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <PageRow
              icon={<Inbox size={14} />}
              name={t("help.name.inbox")}
              href="/"
              line={t("help.page.inbox.desc")}
            />
            <PageRow
              icon={<Layers size={14} />}
              name={t("help.name.workspaces")}
              href="/projects"
              line={t("help.page.workspaces.desc")}
            />
            <PageRow
              icon={<ShieldCheck size={14} />}
              name={t("help.name.approvals")}
              href="/approvals"
              line={t("help.page.approvals.desc")}
            />
            <PageRow
              icon={<KeyRound size={14} />}
              name={t("help.name.artifacts")}
              href="/artifacts"
              line={t("help.page.artifacts.desc")}
            />
            <PageRow
              icon={<Users size={14} />}
              name={t("help.name.agents")}
              href="/agents"
              line={t("help.page.agents.desc")}
            />
            <PageRow
              icon={<Zap size={14} />}
              name={t("help.name.settings")}
              href="/settings"
              line={t("help.page.settings.desc")}
            />
          </div>
        </section>

        {/* Issue detail tabs */}
        <section>
          <h2 className="text-xs font-black uppercase tracking-widest text-text-muted mb-4">
            {t("help.insideIssue")}
          </h2>
          <div className="space-y-2 text-[13px]">
            <FeatureRow
              icon={<Sparkles size={14} />}
              title={t("help.feat.dag")}
              body={t("help.feat.dag.body")}
            />
            <FeatureRow
              icon={<Terminal size={14} />}
              title={t("help.feat.tasks")}
              body={t("help.feat.tasks.body")}
            />
            <FeatureRow
              icon={<KeyRound size={14} />}
              title={t("help.feat.artifacts")}
              body={t("help.feat.artifacts.body")}
            />
            <FeatureRow
              icon={<GitBranch size={14} />}
              title={t("help.feat.diff")}
              body={t("help.feat.diff.body")}
            />
            <FeatureRow
              icon={<MessageSquarePlus size={14} />}
              title={t("help.feat.steer")}
              body={t("help.feat.steer.body")}
            />
            <FeatureRow
              icon={<GitFork size={14} />}
              title={t("help.feat.fork")}
              body={t("help.feat.fork.body")}
            />
            <FeatureRow
              icon={<Undo2 size={14} />}
              title={t("help.feat.undo")}
              body={t("help.feat.undo.body")}
            />
          </div>
        </section>

        {/* Shortcuts */}
        <section>
          <h2 className="text-xs font-black uppercase tracking-widest text-text-muted mb-4">
            {t("help.keyboardShortcuts")}
          </h2>
          <div className="rounded-xl border border-border-subtle bg-surface-raised divide-y divide-border-subtle">
            <ShortcutRow keys={["⌘", "K"]} alt="Ctrl K" desc={t("help.shortcut.cmdK")} />
            <ShortcutRow keys={["alt", "click"]} desc={t("help.shortcut.altClick")} />
            <ShortcutRow keys={["↑", "↓"]} desc={t("help.shortcut.upDown")} />
            <ShortcutRow keys={["↵"]} desc={t("help.shortcut.enter")} />
            <ShortcutRow keys={["esc"]} desc={t("help.shortcut.esc")} />
          </div>
        </section>

        {/* Concepts cheatsheet */}
        <section>
          <h2 className="text-xs font-black uppercase tracking-widest text-text-muted mb-4">
            {t("help.concepts")}
          </h2>
          <ul className="text-[13px] space-y-2 text-text-secondary leading-relaxed">
            <li>
              <b className="text-foreground">{t("help.concept.project")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.project.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.workspace")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.workspace.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.issue")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.issue.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.dag")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.dag.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.task")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.task.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.run")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.run.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.artifact")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.artifact.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.steer")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.steer.body") }} />
            </li>
            <li>
              <b className="text-foreground">{t("help.concept.memory")}</b> — <span dangerouslySetInnerHTML={{ __html: t("help.concept.memory.body") }} />
            </li>
          </ul>
        </section>

    </PageFrame>
  );
}

function Step({
  n,
  icon,
  title,
  body,
  cta,
}: {
  n: number;
  icon: React.ReactNode;
  title: string;
  body: React.ReactNode;
  cta?: { label: string; onClick: () => void };
}) {
  return (
    <li className="enterprise-card rounded-2xl p-4 flex gap-4">
      <div className="size-8 rounded-full bg-brand/10 text-brand flex items-center justify-center font-black tabular-nums shrink-0">
        {n}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-text-muted">{icon}</span>
          <h3 className="text-[14px] font-semibold">{title}</h3>
        </div>
        <div className="text-[13px] text-text-secondary leading-relaxed">{body}</div>
        {cta && (
          <Button
            size="sm"
            variant="outline"
            onClick={cta.onClick}
            className="mt-2 text-[12px]"
          >
            {cta.label} →
          </Button>
        )}
      </div>
    </li>
  );
}

function PageRow({
  icon,
  name,
  href,
  line,
}: {
  icon: React.ReactNode;
  name: string;
  href: string;
  line: string;
}) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={() => router.push(href)}
      className="enterprise-card text-left rounded-2xl px-3.5 py-3 hover:border-brand/40 hover:bg-surface-hover transition-colors flex items-start gap-3"
    >
      <span className="size-7 rounded-md bg-surface-input text-text-muted flex items-center justify-center shrink-0 mt-0.5">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-[13px] font-semibold">{name}</div>
        <div className="text-[11px] text-text-muted leading-snug mt-0.5">{line}</div>
      </div>
    </button>
  );
}

function FeatureRow({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="enterprise-card rounded-2xl px-3.5 py-2.5 flex items-start gap-3">
      <span className="size-6 rounded-md bg-surface-input text-text-muted flex items-center justify-center shrink-0 mt-0.5">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-[13px] font-semibold">{title}</div>
        <div className="text-[12px] text-text-muted leading-relaxed">{body}</div>
      </div>
    </div>
  );
}

function ShortcutRow({
  keys,
  alt,
  desc,
}: {
  keys: string[];
  alt?: string;
  desc: string;
}) {
  return (
    <div className="px-4 py-2.5 flex items-center gap-3">
      <div className="flex items-center gap-1 min-w-[120px]">
        {keys.map((k, i) => (
          <span key={i}>
            <kbd className="text-[11px] px-1.5 py-0.5 rounded bg-surface-input border border-border-subtle font-mono">
              {k}
            </kbd>
            {i < keys.length - 1 && <span className="mx-0.5 text-text-muted">+</span>}
          </span>
        ))}
        {alt && (
          <span className="text-[10px] text-text-muted ml-2">/ {alt}</span>
        )}
      </div>
      <span className="text-[12px] text-text-secondary">{desc}</span>
    </div>
  );
}

function Hop({ children }: { children: React.ReactNode }) {
  return (
    <code className="text-[12px] px-1 rounded bg-surface-input border border-border-subtle">
      {children}
    </code>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="text-[10px] px-1 py-0.5 rounded bg-surface-input border border-border-subtle font-mono">
      {children}
    </kbd>
  );
}

function CheckCircle2Unused() { return <CheckCircle2 />; } // tree-shake guard
export const _UNUSED = CheckCircle2Unused;
