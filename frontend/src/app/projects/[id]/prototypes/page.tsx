import { StructuredPrototypeRoutePage } from "@/features/prototype/structured/StructuredPrototypeRoutePage";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StructuredPrototypeRoutePage projectId={id} />;
}
