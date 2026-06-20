"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { VideoCard } from "@/components/VideoCard";
import { api } from "@/lib/api";
import type { Video } from "@/lib/api";

type Status = "idle" | "loading" | "error" | "ready";

// SearchResults loads public title-search results client-side. The page mounts it
// with key={query}, so the initial status is derived from the query (no
// synchronous setState in the effect) and a new query gives a fresh load.
export function SearchResults({ query }: { query: string }) {
  const trimmed = query.trim();
  const [videos, setVideos] = useState<Video[]>([]);
  const [status, setStatus] = useState<Status>(trimmed ? "loading" : "idle");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!trimmed) return;
    const controller = new AbortController();
    api
      .searchVideos(trimmed, {}, controller.signal)
      .then((res) => {
        setVideos(res.videos);
        setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("error");
      });
    return () => controller.abort();
  }, [trimmed, reloadKey]);

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  if (!trimmed) {
    return <EmptyState title="Search for videos" message="Enter a search term above." />;
  }
  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Searching" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Search failed. Please try again." onRetry={retry} />;
  }
  if (videos.length === 0) {
    return <EmptyState title="No results" message={`Nothing matched “${trimmed}”.`} />;
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
