import { SavedVideosView } from "@/components/SavedVideosView";

export default function LibraryPage() {
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Library</h1>
      <SavedVideosView />
    </main>
  );
}
