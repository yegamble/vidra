"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { VideoCard } from "@/components/VideoCard";
import { ApiError, api } from "@/lib/api";
import type { Channel, Video } from "@/lib/api";
import { formatCount } from "@/lib/format";

type Status = "loading" | "notfound" | "error" | "ready";

// ChannelView loads a channel and its videos client-side. The page mounts it with
// key={handle} so the initial status is "loading" (no synchronous setState in the
// effect) and a new handle gives a fresh load.
export function ChannelView({ handle }: { handle: string }) {
  const [status, setStatus] = useState<Status>("loading");
  const [channel, setChannel] = useState<Channel | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      api.getChannel(handle, controller.signal),
      api.listChannelVideos(handle, undefined, controller.signal),
    ])
      .then(([ch, list]) => {
        setChannel(ch);
        setVideos(list.videos);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setStatus(err instanceof ApiError && err.status === 404 ? "notfound" : "error");
      });
    return () => controller.abort();
  }, [handle, reloadKey]);

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading channel" />
      </div>
    );
  }
  if (status === "notfound") {
    return <EmptyState title="Channel not found" message={`No channel @${handle} exists.`} />;
  }
  if (status === "error" || channel === null) {
    return <ErrorState message="Could not load this channel." onRetry={retry} />;
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2 border-b border-zinc-200 pb-6 dark:border-zinc-800">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              {channel.display_name || channel.handle}
            </h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              @{channel.handle} · {formatCount(channel.follower_count)} followers
            </p>
          </div>
          <SubscribeButton
            handle={channel.handle}
            onDelta={(d) =>
              setChannel((c) => (c ? { ...c, follower_count: Math.max(0, c.follower_count + d) } : c))
            }
          />
        </div>
        {channel.description ? (
          <p className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">
            {channel.description}
          </p>
        ) : null}
      </header>

      {videos.length === 0 ? (
        <EmptyState title="No videos yet" message="This channel has not published anything." />
      ) : (
        <ul className="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {videos.map((video) => (
            <li key={video.id}>
              <VideoCard video={video} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// SubscribeButton toggles a follow on the channel for the signed-in user. The
// public channel endpoint carries no "is following" flag, so the button starts
// at "Subscribe" and tracks state locally (follow/unfollow are idempotent
// server-side); onDelta nudges the displayed follower count optimistically.
// Anonymous visitors get a sign-in link instead.
function SubscribeButton({ handle, onDelta }: { handle: string; onDelta: (d: number) => void }) {
  const { status } = useSession();
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);

  if (status !== "authed") {
    return (
      <Link
        href="/login"
        className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      >
        Sign in to subscribe
      </Link>
    );
  }

  async function toggle() {
    setBusy(true);
    const next = !subscribed;
    try {
      if (next) {
        await api.followChannel(handle);
      } else {
        await api.unfollowChannel(handle);
      }
      setSubscribed(next);
      onDelta(next ? 1 : -1);
    } catch {
      // Leave the button state unchanged on failure.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => void toggle()}
      className={
        subscribed
          ? "rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          : "rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      }
    >
      {subscribed ? "Subscribed" : "Subscribe"}
    </button>
  );
}
