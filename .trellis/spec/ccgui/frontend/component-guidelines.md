# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

(To be filled by the team)

---

## Component Structure

<!-- Standard structure of a component file -->

(To be filled by the team)

---

## Props Conventions

<!-- How props should be defined and typed -->

(To be filled by the team)

---

## Styling Patterns

<!-- How styles are applied (CSS modules, styled-components, Tailwind, etc.) -->

### Convention: Enterprise Workbench Surfaces

**What**: Top-level workbench pages should use `PageFrame` for the page hero and global surface utilities from `frontend/src/app/globals.css` for major panels.

**Why**: The app is a multi-agent operations console. Reusing `PageFrame`, `enterprise-panel`, `enterprise-card`, `agent-mesh-grid`, `agent-orb`, and `agent-rail` keeps shell, issue, project, approval, artifact, knowledge, settings, and help pages visually coherent instead of drifting into unrelated one-off cards.

**Example**:
```tsx
<PageFrame
  eyebrow="approvals"
  title="Approvals"
  description="Review the things waiting on you across every project."
  contentClassName="space-y-5"
>
  <section className="enterprise-panel rounded-2xl">
    ...
  </section>
</PageFrame>
```

**Avoid**: Creating new page-level gradients, mesh patterns, or shadow recipes inside individual feature pages unless the shared utility cannot express the design. Prefer adding a shared utility first when the pattern should apply across pages.

### Convention: Shared Interaction State

**What**: Workflow attention, next-action, and recovery affordances should be derived in pure helpers before rendering UI.

**Why**: Multi-agent screens reuse the same concepts across Shell, Inbox, Issue Detail, Tasks/Runs, and Approvals. Pure helpers such as `deriveAttentionItems`, `deriveIssueNextAction`, and `deriveRunRecoveryActions` make those rules testable and keep pages from drifting into inconsistent interaction logic.

**Example**:
```tsx
const nextAction = deriveIssueNextAction({
  issue,
  tasks: issueTasks,
  artifacts: issueArtifacts,
});

return <IssueActionStrip action={nextAction} onPrimary={handlePrimary} />;
```

**Avoid**: Recomputing the same status priority or disabled-reason rules inline in page components. Add or extend a helper in `frontend/src/features/workbench/interaction/` and cover it with a focused test.

---

## Accessibility

<!-- A11y requirements and patterns -->

(To be filled by the team)

---

## Common Mistakes

<!-- Component-related mistakes your team has made -->

(To be filled by the team)
