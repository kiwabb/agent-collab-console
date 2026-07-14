import { StructuredPrototypeStudioPage } from "@/features/prototype/structured/StructuredPrototypeStudioPage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StructuredPrototypeStudioPage projectId={id} />;
}
