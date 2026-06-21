"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { api } from "@/lib/api";

// SaveButton toggles a video in the signed-in viewer's library ("watch later").
// On mount it reads the library to reflect whether this video is already saved;
// clicking saves or unsaves, with the server treated as the source of truth.
export function SaveButton({ videoId }: { videoId: string }) {
  const { status } = useSession();
  const [saved, setSaved] = useState<boolean | null>(null); // null = not yet known
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (status !== "authed") return;
    const controller = new AbortController();
    api
      .getSavedVideos({ limit: 100 }, controller.signal)
      .then((res) => setSaved(res.videos.some((v) => v.id === videoId)))
      .catch(() => {
        if (!controller.signal.aborted) setSaved(false);
      });
    return () => controller.abort();
  }, [videoId, status]);

  if (status !== "authed") {
    return (
      <Link
        href="/login"
        className="rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      >
        Sign in to save
      </Link>
    );
  }

  async function toggle() {
    if (busy || saved === null) return;
    setBusy(true);
    const next = !saved;
    try {
      if (next) {
        await api.saveVideo(videoId);
      } else {
        await api.unsaveVideo(videoId);
      }
      setSaved(next);
    } catch {
      // Keep the current state on failure.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      aria-pressed={saved === true}
      disabled={busy || saved === null}
      onClick={() => void toggle()}
      className={
        "flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 " +
        (saved
          ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
          : "border-zinc-300 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800")
      }
    >
      <span aria-hidden>{saved ? "★" : "☆"}</span>
      <span>{saved ? "Saved" : "Save"}</span>
    </button>
  );
}
