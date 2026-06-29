import { WatchHistoryView } from "@/components/WatchHistoryView";

export default function HistoryPage() {
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">History</h1>
      <WatchHistoryView />
    </main>
  );
}
