import { AdminCommentsView } from "@/components/AdminCommentsView";
import { ModerationTabs } from "@/components/ModerationTabs";

export default function AdminCommentsPage() {
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Moderation</h1>
      <p className="mb-6 text-sm text-zinc-500 dark:text-zinc-400">
        Every comment on the instance. Delete any that violate the rules.
      </p>
      <ModerationTabs />
      <AdminCommentsView />
    </main>
  );
}
