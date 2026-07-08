import type { PrototypeCodeCandidate } from "../../lib/types";

export function isCodeCandidateBriefModified(
  candidate: PrototypeCodeCandidate,
  candidateBriefs: Record<string, string>,
): boolean {
  const current = (candidateBriefs[candidate.id] ?? candidate.editable_brief).trim();
  return Boolean(current) && current !== candidate.editable_brief.trim();
}

export function buildCodeCandidateBriefOverrides(
  candidates: PrototypeCodeCandidate[],
  selectedCandidateIds: string[],
  candidateBriefs: Record<string, string>,
): Record<string, string> {
  const selected = new Set(selectedCandidateIds);
  const overrides: Record<string, string> = {};
  for (const candidate of candidates) {
    if (!selected.has(candidate.id)) continue;
    if (!isCodeCandidateBriefModified(candidate, candidateBriefs)) continue;
    overrides[candidate.id] = (candidateBriefs[candidate.id] ?? "").trim();
  }
  return overrides;
}

export function buildSelectedCodeCandidateInstructions(
  selectedCandidateIds: string[],
  candidateInstructions: Record<string, string>,
): Record<string, string> {
  const selected = new Set(selectedCandidateIds);
  const instructions: Record<string, string> = {};
  for (const [candidateId, instruction] of Object.entries(candidateInstructions)) {
    const clean = instruction.trim();
    if (selected.has(candidateId) && clean) {
      instructions[candidateId] = clean;
    }
  }
  return instructions;
}

export function countModifiedCodeCandidateBriefs(
  candidates: PrototypeCodeCandidate[],
  selectedCandidateIds: string[],
  candidateBriefs: Record<string, string>,
): number {
  return Object.keys(
    buildCodeCandidateBriefOverrides(candidates, selectedCandidateIds, candidateBriefs),
  ).length;
}
