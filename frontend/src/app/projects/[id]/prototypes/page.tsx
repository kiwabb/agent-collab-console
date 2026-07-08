import { ProjectPrototypesRoutePage } from "@/features/prototype/ProjectPrototypesRoutePage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProjectPrototypesRoutePage projectId={id} />;
}
