import { PlaylistsView } from "@/components/PlaylistsView";

export default function PlaylistsPage() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Playlists</h1>
      <PlaylistsView />
    </main>
  );
}
