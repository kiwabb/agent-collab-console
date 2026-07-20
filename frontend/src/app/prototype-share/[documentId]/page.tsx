import { StructuredPrototypeShareViewer } from "@/features/prototype/structured/StructuredPrototypeShareViewer";

export default async function StructuredPrototypeSharePage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  return <StructuredPrototypeShareViewer documentId={documentId} />;
}
