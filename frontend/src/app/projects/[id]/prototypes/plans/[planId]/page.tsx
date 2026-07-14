import { PrototypePlanRoutePage } from "@/features/prototype/PrototypePlanRoutePage";

export default async function Page({
  params,
}: {
  params: Promise<{ id: string; planId: string }>;
}) {
  const { id, planId } = await params;
  return <PrototypePlanRoutePage projectId={id} planId={planId} />;
}
