import { ProjectEnvConfigRoutePage } from "@/features/projects/ProjectEnvConfigRoutePage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProjectEnvConfigRoutePage projectId={id} />;
}
