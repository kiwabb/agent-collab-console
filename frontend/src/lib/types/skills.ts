// AUTO-SPLIT from lib/types.ts by domain (frontend lib split).

export interface Skill {
  id: string;
  name: string;
  link: string;
  description: string | null;
  category: string | null;
  tags: string[];
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateSkillRequest {
  name: string;
  link: string;
  description?: string | null;
  category?: string | null;
  tags?: string[];
}

export type UpdateSkillRequest = Partial<CreateSkillRequest>;

export interface SkillImportResult {
  created: Skill[];
  skipped: Array<{ file?: string; row?: string; reason: string }>;
}
