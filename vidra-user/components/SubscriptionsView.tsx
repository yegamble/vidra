"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { VideoCard } from "@/components/VideoCard";
import { api } from "@/lib/api";
import type { Video } from "@/lib/api";

type Status = "loading" | "error" | "ready";

// SubscriptionsView shows the signed-in user's feed of videos from the channels
// they follow. The session lives in memory, so a hard reload lands here signed
// out — we show a sign-in prompt rather than fetching.
export function SubscriptionsView() {
  const { status } = useSession();

  if (status !== "authed") {
    return (
      <EmptyState
        title="Sign in to see your subscriptions"
        message={
          <>
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to follow channels and watch their latest videos here.
          </>
        }
      />
    );
  }

  return <Feed />;
}

function Feed() {
  const [status, setStatus] = useState<Status>("loading");
  const [videos, setVideos] = useState<Video[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getSubscriptionVideos({}, controller.signal)
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

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading subscriptions" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Could not load your subscriptions." onRetry={retry} />;
  }
  if (videos.length === 0) {
    return (
      <EmptyState
        title="No videos from your subscriptions yet"
        message="Subscribe to channels and their latest videos will show up here."
      />
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {videos.map((video) => (
        <li key={video.id}>
          <VideoCard video={video} />
        </li>
      ))}
    </ul>
  );
}
