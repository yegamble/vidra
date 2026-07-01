"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { AddToPlaylistButton } from "@/components/AddToPlaylistButton";
import { CommentsSection } from "@/components/CommentsSection";
import { RatingControls } from "@/components/RatingControls";
import { ReportButton } from "@/components/ReportButton";
import { SaveButton } from "@/components/SaveButton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api, videoCaptionUrl, videoOriginalUrl, videoThumbnailUrl } from "@/lib/api";
import type { Video } from "@/lib/api";
import { formatCount, formatDuration, relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "notfound" | "ready";

// How often, at most, playback progress is reported to the backend while watching.
const PROGRESS_INTERVAL_MS = 10_000;
// Only offer to resume when the saved position is past this many seconds (skip
// trivial positions a viewer would not want to "resume" into).
const RESUME_MIN_SECONDS = 5;

// WatchView loads one video client-side and plays its original via a Range-capable
// <video src>. States: loading / not-found (404) / error (retry) / ready. For a
// signed-in viewer it records watch progress (so the video enters their history
// and can be resumed) and offers a Resume control from the saved position.
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
    <div className="flex flex-col gap-8">
      <article className="flex flex-col gap-4">
        <Player video={video} />

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
          <div className="flex flex-wrap items-center gap-2">
            <RatingControls videoId={video.id} />
            <SaveButton videoId={video.id} />
            <AddToPlaylistButton videoId={video.id} />
            <ReportButton kind="video" targetId={video.id} />
          </div>
          {video.description ? (
            <p className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">
              {video.description}
            </p>
          ) : null}
        </div>
      </article>

      <CommentsSection videoId={video.id} />
    </div>
  );
}

// Player wraps the native <video> with watch-history behaviour: for a signed-in
// viewer it reports playback position (throttled, plus on pause and unmount) and
// surfaces a Resume control loaded from the saved position.
function Player({ video }: { video: Video }) {
  const { status: sessionStatus } = useSession();
  const authed = sessionStatus === "authed";
  const videoRef = useRef<HTMLVideoElement>(null);
  const lastSentRef = useRef(0);
  const [resumeAt, setResumeAt] = useState<number | null>(null);
  const [tracks, setTracks] = useState<
    Array<{ language: string; label: string; url: string }>
  >([]);

  // Report the current position (whole seconds). No-op unless signed in.
  const record = useCallback(() => {
    const el = videoRef.current;
    if (!authed || !el) return;
    const pos = Math.floor(el.currentTime || 0);
    void api.recordWatchProgress(video.id, pos).catch(() => {});
  }, [authed, video.id]);

  // Throttled variant for the high-frequency timeupdate/play events.
  const recordThrottled = useCallback(() => {
    const now = Date.now();
    if (now - lastSentRef.current < PROGRESS_INTERVAL_MS) return;
    lastSentRef.current = now;
    record();
  }, [record]);

  // Load the saved resume position once (signed in only).
  useEffect(() => {
    if (!authed) return;
    const controller = new AbortController();
    api
      .getWatchProgress(video.id, controller.signal)
      .then((p) => {
        if (p.position_seconds >= RESUME_MIN_SECONDS) setResumeAt(p.position_seconds);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [authed, video.id]);

  // Flush the final position when leaving the page / switching videos.
  useEffect(() => {
    return () => record();
  }, [record]);

  // Load the video's caption tracks and expose each WebVTT body as a same-origin
  // blob URL. Fetching the text ourselves (rather than pointing <track src> at the
  // cross-origin backend) sidesteps the native cross-origin track restriction — no
  // `crossorigin` on the media element, so the Range-based stream is untouched.
  // Captions are small; loading them up front is cheap and revoked on cleanup.
  useEffect(() => {
    const controller = new AbortController();
    const created: string[] = [];
    let cancelled = false;
    api
      .getCaptions(video.id, controller.signal)
      .then(async ({ captions }) => {
        const loaded: Array<{ language: string; label: string; url: string }> = [];
        for (const c of captions) {
          try {
            const res = await fetch(videoCaptionUrl(video.id, c.language), {
              signal: controller.signal,
            });
            if (!res.ok) continue;
            const url = URL.createObjectURL(
              new Blob([await res.text()], { type: "text/vtt" }),
            );
            created.push(url);
            loaded.push({ language: c.language, label: c.label || c.language, url });
          } catch {
            // Skip a track that fails to load; the others still work.
          }
        }
        if (!cancelled) setTracks(loaded);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      controller.abort();
      created.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [video.id]);

  function resume() {
    const el = videoRef.current;
    if (el && resumeAt !== null) {
      el.currentTime = resumeAt;
      void el.play().catch(() => {});
    }
    setResumeAt(null);
  }

  return (
    <div className="flex flex-col gap-2">
      <video
        ref={videoRef}
        controls
        playsInline
        className="aspect-video w-full rounded-lg bg-black"
        src={videoOriginalUrl(video.id)}
        poster={video.has_thumbnail ? videoThumbnailUrl(video.id) : undefined}
        onPlay={recordThrottled}
        onTimeUpdate={recordThrottled}
        onPause={record}
      >
        {tracks.map((t) => (
          <track key={t.language} kind="captions" srcLang={t.language} label={t.label} src={t.url} />
        ))}
        Your browser does not support the video tag.
      </video>
      {resumeAt !== null ? (
        <button
          type="button"
          onClick={resume}
          className="self-start rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          Resume from {formatDuration(resumeAt)}
        </button>
      ) : null}
    </div>
  );
}
