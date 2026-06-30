import { ModerationQueue } from "@/components/ModerationQueue";

export default function ModerationPage() {
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8">
      <h1 className="mb-1 text-2xl font-semibold tracking-tight">Moderation</h1>
      <p className="mb-6 text-sm text-zinc-500 dark:text-zinc-400">
        Review and resolve abuse reports filed by viewers.
      </p>
      <ModerationQueue />
    </main>
  );
}
