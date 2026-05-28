/**
 * Shared formatting utilities for displaying tokens, costs, durations, etc.
 */

export function formatTok(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

export function formatCost(usd: number | null | undefined): string {
  if (usd == null) return "";
  return `$${usd.toFixed(3)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const totalSeconds = Math.round(seconds);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  if (secs === 0) return `${minutes}m`;
  return `${minutes}m ${secs}s`;
}
