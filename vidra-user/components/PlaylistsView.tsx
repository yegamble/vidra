"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import type { Playlist, PlaylistVisibility } from "@/lib/api";

type Status = "loading" | "error" | "ready";

// PlaylistsView lists the signed-in user's playlists and offers an inline create
// form. The session lives in memory, so a hard reload lands here signed out.
export function PlaylistsView() {
  const { status } = useSession();

  if (status !== "authed") {
    return (
      <EmptyState
        title="Sign in to see your playlists"
        message={
          <>
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to create playlists and organise videos.
          </>
        }
      />
    );
  }

  return <Playlists />;
}

function Playlists() {
  const [status, setStatus] = useState<Status>("loading");
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  const [title, setTitle] = useState("");
  const [visibility, setVisibility] = useState<PlaylistVisibility>("private");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getMyPlaylists(controller.signal)
      .then((res) => {
        setPlaylists(res.playlists);
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

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const t = title.trim();
    if (creating || t === "") return;
    setCreating(true);
    setCreateError(null);
    try {
      const pl = await api.createPlaylist({ title: t, visibility });
      setPlaylists((list) => [pl, ...list]);
      setTitle("");
      setVisibility("private");
    } catch {
      setCreateError("Could not create the playlist.");
    } finally {
      setCreating(false);
    }
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading your playlists" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Could not load your playlists." onRetry={retry} />;
  }

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={(e) => void create(e)}
        className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 sm:flex-row sm:items-end dark:border-zinc-800"
      >
        <label className="flex flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">New playlist</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Playlist title"
            aria-label="Playlist title"
            maxLength={200}
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Visibility</span>
          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as PlaylistVisibility)}
            aria-label="Visibility"
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          >
            <option value="private">Private</option>
            <option value="unlisted">Unlisted</option>
            <option value="public">Public</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={creating || title.trim() === ""}
          className="rounded-full bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Create
        </button>
      </form>
      {createError ? <p className="text-sm text-red-600">{createError}</p> : null}

      {playlists.length === 0 ? (
        <EmptyState
          title="No playlists yet"
          message="Create a playlist above, then add videos to it from any watch page."
        />
      ) : (
        <ul className="flex flex-col divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {playlists.map((pl) => (
            <li key={pl.id}>
              <Link
                href={`/playlists/${pl.id}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:hover:bg-zinc-900/40"
              >
                <span className="min-w-0 flex-1 truncate font-medium">{pl.title}</span>
                <span className="shrink-0 text-xs text-zinc-500 dark:text-zinc-400">
                  {pl.video_count} {pl.video_count === 1 ? "video" : "videos"} · {pl.visibility}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
