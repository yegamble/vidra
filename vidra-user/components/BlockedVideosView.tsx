"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { BlockedVideo } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "ready";

// BlockedVideosView is the moderator/admin block-list: every currently-blocked
// video with the context to review it (channel, reason, who blocked it, when) and
// an Unblock control. A non-privileged or anonymous viewer is gated out (the
// session lives in memory, so a hard reload lands here signed out — show a prompt
// rather than fetching a 403).
export function BlockedVideosView() {
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
            with a moderator account to review blocked videos.
          </>
        }
      />
    );
  }

  return <BlockList />;
}

function BlockList() {
  const [status, setStatus] = useState<Status>("loading");
  const [videos, setVideos] = useState<BlockedVideo[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getBlockedVideos({ limit: 100 }, controller.signal)
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
  }, [reloadKey]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }, []);

  // After an unblock, drop the row locally so it disappears immediately; a later
  // refetch confirms persistence.
  const onUnblocked = useCallback((id: string) => {
    setVideos((prev) => prev.filter((v) => v.video_id !== id));
  }, []);

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading blocked videos" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Could not load the block-list." onRetry={retry} />;
  }
  if (videos.length === 0) {
    return (
      <EmptyState
        title="No blocked videos"
        message="When a moderator blocks a video it is hidden from public surfaces and listed here."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {videos.map((video) => (
        <li key={video.video_id}>
          <BlockedRow video={video} onUnblocked={onUnblocked} />
        </li>
      ))}
    </ul>
  );
}

type RowState = "idle" | "submitting";

function BlockedRow({
  video,
  onUnblocked,
}: {
  video: BlockedVideo;
  onUnblocked: (id: string) => void;
}) {
  const [rowState, setRowState] = useState<RowState>("idle");
  const [error, setError] = useState<string | null>(null);

  async function unblock() {
    if (rowState === "submitting") return;
    setRowState("submitting");
    setError(null);
    try {
      await api.unblockVideo(video.video_id);
      onUnblocked(video.video_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not unblock this video.");
      setRowState("idle");
    }
  }

  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/videos/${video.video_id}`}
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
            <span>blocked {relativeTime(video.blocked_at)}</span>
            {video.blocked_by ? (
              <>
                <span aria-hidden> · </span>
                <span>
                  by <span className="font-medium text-zinc-700 dark:text-zinc-200">{video.blocked_by}</span>
                </span>
              </>
            ) : null}
          </p>
        </div>
        <button
          type="button"
          disabled={rowState === "submitting"}
          onClick={() => void unblock()}
          className="shrink-0 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          Unblock
        </button>
      </div>

      {video.reason ? (
        <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
          <span className="font-medium">Reason:</span> {video.reason}
        </p>
      ) : null}

      {error ? <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
    </article>
  );
}
