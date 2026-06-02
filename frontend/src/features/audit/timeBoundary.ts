/**
 * Helpers to normalize `datetime-local` minute-precision values into full
 * inclusive sub-second boundaries before sending them to the audit-log query.
 *
 * The backend stores `created_at` with microsecond precision and compares
 * lexicographically as ISO-8601 strings. A bare minute-precision value
 * (`2026-06-02T14:30`) breaks the upper bound (`until`) because a longer
 * microsecond string sorts after the minute prefix, so events within the
 * boundary minute would be silently dropped. Pad to seconds so the comparison
 * is correct regardless of the stored sub-minute precision.
 */

/** True when the value is bare minute precision: `YYYY-MM-DDTHH:MM` (no seconds). */
const MINUTE_PRECISION = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** Normalize the `since` (lower bound) to the start of the value. */
export function normalizeSince(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return MINUTE_PRECISION.test(trimmed) ? `${trimmed}:00` : trimmed;
}

/** Normalize the `until` (upper bound) to the inclusive end of the value. */
export function normalizeUntil(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  return MINUTE_PRECISION.test(trimmed) ? `${trimmed}:59.999999` : trimmed;
}
