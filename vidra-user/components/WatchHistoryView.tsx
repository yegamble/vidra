"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { VideoCard } from "@/components/VideoCard";
import { api } from "@/lib/api";
import type { HistoryItem } from "@/lib/api";
import { formatDuration, relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "ready";

// WatchHistoryView shows the signed-in user's watch history (most-recently
// watched first) with a per-item remove and a clear-all control. The session
// lives in memory, so a hard reload lands here signed out — we prompt to sign in.
export function WatchHistoryView() {
  const { status } = useSession();

  if (status !== "authed") {
    return (
      <EmptyState
        title="Sign in to see your history"
        message={
          <>
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to keep track of what you have watched.
          </>
        }
      />
    );
  }

  return <History />;
}

function History() {
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const [clearing, setClearing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getWatchHistory({}, controller.signal)
      .then((res) => {
        setItems(res.videos);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [reloadKey]);

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  async function remove(id: string) {
    const prev = items;
    setItems((list) => list.filter((it) => it.id !== id)); // optimistic
    try {
      await api.deleteHistoryEntry(id);
    } catch {
      setItems(prev); // restore on failure
    }
  }

  async function clearAll() {
    if (clearing) return;
    setClearing(true);
    const prev = items;
    setItems([]); // optimistic
    try {
      await api.clearWatchHistory();
    } catch {
      setItems(prev);
    } finally {
      setClearing(false);
    }
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading your history" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Could not load your history." onRetry={retry} />;
  }
  if (items.length === 0) {
    return (
      <EmptyState
        title="No watch history yet"
        message="Videos you watch will show up here so you can pick up where you left off."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void clearAll()}
          disabled={clearing}
          className="text-sm font-medium text-zinc-600 hover:text-zinc-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:text-zinc-300 dark:hover:text-zinc-100"
        >
          Clear all history
        </button>
      </div>
      <ul className="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {items.map((item) => (
          <li key={item.id} className="flex flex-col gap-2">
            <VideoCard video={item} />
            <div className="flex items-center justify-between gap-2 text-xs text-zinc-500 dark:text-zinc-400">
              <span>
                {item.position_seconds > 0
                  ? `Resume at ${formatDuration(item.position_seconds)}`
                  : "Watched"}
                {item.watched_at ? ` · ${relativeTime(item.watched_at)}` : ""}
              </span>
              <button
                type="button"
                onClick={() => void remove(item.id)}
                aria-label={`Remove ${item.title} from history`}
                className="shrink-0 font-medium hover:text-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:hover:text-zinc-200"
              >
                Remove
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
