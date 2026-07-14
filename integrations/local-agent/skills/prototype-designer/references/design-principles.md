# Structured Prototype Design Principles

## Structure

- Model pages, components, component instances, tokens, and runtime flows as distinct semantic entities.
- Reuse components for repeated business patterns. Preserve meaningful instance overrides instead of detaching copies.
- Use constraints for alignment, spacing, sizing, wrapping, and responsive behavior. Avoid coordinate-only placement for normal application layouts.

## Product Workflows

- Represent navigation and state transitions explicitly, including role or permission conditions.
- Keep business actions traceable from trigger through validation, confirmation, result, and downstream status changes.
- Add empty, loading, error, disabled, success, and stale states when they can occur in the real workflow.
- Preserve data relationships across detail, list, dashboard, and approval views so a runtime transition can update every dependent view.

## Visual System

- Reuse named color, typography, spacing, radius, and elevation tokens.
- Maintain contrast, focus indication, keyboard reachability, and readable control labels.
- Use familiar controls for their intended behavior: buttons for commands, tabs for views, menus for option sets, and toggles for binary settings.
- Keep operational products dense, predictable, and easy to scan. Avoid decorative layout changes that obscure business state.

## Reviewability

- Keep each proposal focused enough for a product manager to understand in Preview.
- Summarize user-visible intent, not internal implementation steps.
- Split unrelated visual cleanup and workflow behavior into separate proposals.
