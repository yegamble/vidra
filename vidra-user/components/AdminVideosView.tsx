"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { AdminVideo } from "@/lib/api";
import { formatCount, relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "ready";

// AdminVideosView is the moderator/admin videos overview: browse every video
// (any privacy/state) and block/unblock any of them. A non-privileged or
// anonymous viewer is gated out (the session lives in memory, so a hard reload
// lands here signed out — show a prompt rather than fetching a 403).
export function AdminVideosView() {
  const { user } = useSession();
  const role = user?.role;

  if (role !== "admin" && role !== "moderator") {
    return (
      <EmptyState
        title="Moderators only"
        message={
          <>
            This page is for moderators and administrators.{" "}
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            with a moderator account to manage videos.
          </>
        }
      />
    );
  }

  return <VideosList />;
}

function VideosList() {
  const [status, setStatus] = useState<Status>("loading");
  const [videos, setVideos] = useState<AdminVideo[]>([]);
  const [query, setQuery] = useState("");
  const [input, setInput] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getAdminVideos({ q: query || undefined, limit: 100 }, controller.signal)
      .then((res) => {
        setVideos(res.videos);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [query, reloadKey]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }, []);

  const submitSearch = useCallback(
    (next: string) => {
      if (next === query) return;
      setStatus("loading");
      setQuery(next);
    },
    [query],
  );

  // Reflect a block/unblock back into the row.
  const onBlockedChange = useCallback((id: string, blocked: boolean) => {
    setVideos((prev) => prev.map((v) => (v.id === id ? { ...v, blocked } : v)));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <form
        role="search"
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submitSearch(input.trim());
        }}
      >
        <input
          type="search"
          aria-label="Search videos by title"
          placeholder="Search by title"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="w-full max-w-sm rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Search
        </button>
        {query ? (
          <button
            type="button"
            onClick={() => {
              setInput("");
              submitSearch("");
            }}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            Clear
          </button>
        ) : null}
      </form>

      {status === "loading" ? (
        <div className="flex justify-center py-24">
          <Spinner label="Loading videos" />
        </div>
      ) : status === "error" ? (
        <ErrorState message="Could not load videos." onRetry={retry} />
      ) : videos.length === 0 ? (
        <EmptyState
          title={query ? "No matching videos" : "No videos yet"}
          message={query ? "Try a different search term." : "Videos will appear here as they are published."}
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {videos.map((v) => (
            <li key={v.id}>
              <VideoRow video={v} onBlockedChange={onBlockedChange} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const PRIVACY_STYLE: Record<string, string> = {
  public: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  unlisted: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  private: "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
};

function VideoRow({
  video,
  onBlockedChange,
}: {
  video: AdminVideo;
  onBlockedChange: (id: string, blocked: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleBlock() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (video.blocked) {
        await api.unblockVideo(video.id);
        onBlockedChange(video.id, false);
      } else {
        await api.blockVideo(video.id);
        onBlockedChange(video.id, true);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update this video.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/videos/${video.id}`}
            className="font-medium text-zinc-900 underline hover:text-zinc-700 dark:text-zinc-100 dark:hover:text-zinc-300"
          >
            {video.title || "Untitled video"}
          </Link>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            <Link
              href={`/channels/${video.channel_handle}`}
              className="hover:text-zinc-700 dark:hover:text-zinc-200"
            >
              {video.channel_display_name || video.channel_handle}
            </Link>
            <span aria-hidden> · </span>
            <span>{formatCount(video.views)} views</span>
            <span aria-hidden> · </span>
            <span>{relativeTime(video.created_at)}</span>
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PRIVACY_STYLE[video.privacy] ?? PRIVACY_STYLE.private}`}>
              {video.privacy}
            </span>
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              {video.state}
            </span>
            {video.blocked ? (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/40 dark:text-red-300">
                blocked
              </span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void toggleBlock()}
          className={
            video.blocked
              ? "shrink-0 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
              : "shrink-0 rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-60 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40"
          }
        >
          {video.blocked ? "Unblock" : "Block"}
        </button>
      </div>
      {error ? <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
    </article>
  );
}
