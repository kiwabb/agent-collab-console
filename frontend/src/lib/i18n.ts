// Re-export from the split layout. Kept so existing imports
// `from "@/lib/i18n"` continue to resolve to the same surface.
// Phase 4 follow-up: migrate consumers to `from "@/lib/i18n"` and
// `from "@/lib/i18n/<locale>"` directly, then delete this stub.

export * from "./i18n/index";
