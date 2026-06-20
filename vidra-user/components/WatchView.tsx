"use client";

import { useEffect, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api, videoOriginalUrl, videoThumbnailUrl } from "@/lib/api";
import type { Video } from "@/lib/api";
import { formatCount, formatDuration, relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "notfound" | "ready";

// WatchView loads one video client-side and plays its original via a Range-capable
// <video src>. States: loading / not-found (404) / error (retry) / ready.
export function WatchView({ id }: { id: string }) {
  const [status, setStatus] = useState<Status>("loading");
  const [video, setVideo] = useState<Video | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getVideo(id, undefined, controller.signal)
      .then((v) => {
        setVideo(v);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setStatus(err instanceof ApiError && err.status === 404 ? "notfound" : "error");
      });
    return () => controller.abort();
  }, [id, reloadKey]);

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading video" />
      </div>
    );
  }
  if (status === "notfound") {
    return (
      <EmptyState
        title="Video not found"
        message="This video does not exist, or it is private."
      />
    );
  }
  if (status === "error" || video === null) {
    return <ErrorState message="Could not load this video." onRetry={retry} />;
  }

  const meta: string[] = [];
  if (typeof video.views === "number") meta.push(`${formatCount(video.views)} views`);
  const when = relativeTime(video.created_at);
  if (when) meta.push(when);

  const chips: string[] = [];
  if (typeof video.duration_seconds === "number") chips.push(formatDuration(video.duration_seconds));
  if (typeof video.width === "number" && typeof video.height === "number") {
    chips.push(`${video.width}×${video.height}`);
  }

  return (
    <article className="flex flex-col gap-4">
      <video
        controls
        playsInline
        className="aspect-video w-full rounded-lg bg-black"
        src={videoOriginalUrl(video.id)}
        poster={video.has_thumbnail ? videoThumbnailUrl(video.id) : undefined}
      >
        Your browser does not support the video tag.
      </video>

      <div className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold tracking-tight">{video.title}</h1>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-500 dark:text-zinc-400">
          {meta.length > 0 ? <span>{meta.join(" · ")}</span> : null}
          {chips.map((c) => (
            <span
              key={c}
              className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
            >
              {c}
            </span>
          ))}
        </div>
        {video.description ? (
          <p className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">
            {video.description}
          </p>
        ) : null}
      </div>
    </article>
  );
}
