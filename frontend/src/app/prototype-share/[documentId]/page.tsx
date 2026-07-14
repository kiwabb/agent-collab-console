export default async function StructuredPrototypeSharePage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  const source = `/api/structured-prototype-public/${encodeURIComponent(documentId)}/current/index.html`;

  return (
    <main className="h-dvh w-full overflow-hidden bg-white">
      <iframe
        className="h-full w-full border-0"
        src={source}
        title="Published structured prototype"
        sandbox="allow-scripts allow-same-origin"
      />
    </main>
  );
}
