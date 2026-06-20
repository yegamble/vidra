"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { VideoCard } from "@/components/VideoCard";
import { api } from "@/lib/api";
import type { Video } from "@/lib/api";

type Status = "loading" | "error" | "ready";

// VideoFeed loads the public feed in the browser (so it is route-mockable in
// tests and refetchable) and renders loading / error / empty / grid states. The
// API client already logs failures; this component only reflects them in the UI.
export function VideoFeed() {
  const [status, setStatus] = useState<Status>("loading");
  const [videos, setVideos] = useState<Video[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getFeed({}, controller.signal)
      .then((res) => {
        setVideos(res.videos);
        setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("error");
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
        <Spinner label="Loading videos" />
      </div>
    );
  }
  if (status === "error") {
    return (
      <ErrorState
        message="Could not load videos. The backend may be unavailable."
        onRetry={retry}
      />
    );
  }
  if (videos.length === 0) {
    return <EmptyState title="No videos yet" message="Published videos will appear here." />;
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
