import type { ReactNode } from "react";

export function EmptyState({ title, message }: { title: string; message?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-300 px-6 py-16 text-center dark:border-zinc-700">
      <p className="text-lg font-medium text-zinc-700 dark:text-zinc-200">{title}</p>
      {message ? <p className="max-w-sm text-sm text-zinc-500 dark:text-zinc-400">{message}</p> : null}
    </div>
  );
}
