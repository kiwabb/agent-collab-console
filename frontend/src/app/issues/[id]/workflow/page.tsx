import { IssueWorkflowPage } from "@/features/workflow/IssueWorkflowPage";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function Page({ params }: Props) {
  const { id } = await params;
  return <IssueWorkflowPage issueId={id} />;
}
