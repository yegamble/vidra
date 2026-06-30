import { PlaylistDetailView } from "@/components/PlaylistDetailView";

export default async function PlaylistDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
      <PlaylistDetailView id={id} />
    </main>
  );
}
