import { AdminVideosView } from "@/components/AdminVideosView";
import { ModerationTabs } from "@/components/ModerationTabs";

export default function AdminVideosPage() {
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Moderation</h1>
      <p className="mb-6 text-sm text-zinc-500 dark:text-zinc-400">
        Every video on the instance. Block one to hide it from public surfaces.
      </p>
      <ModerationTabs />
      <AdminVideosView />
    </main>
  );
}
