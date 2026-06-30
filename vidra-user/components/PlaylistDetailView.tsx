"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { VideoCard } from "@/components/VideoCard";
import { ApiError, api } from "@/lib/api";
import type { PlaylistDetail } from "@/lib/api";

type Status = "loading" | "error" | "notfound" | "ready";

// PlaylistDetailView shows a playlist and its videos. Owner-only controls (remove
// item, delete playlist) appear when the playlist is one of the viewer's own.
export function PlaylistDetailView({ id }: { id: string }) {
  const router = useRouter();
  const { status: session } = useSession();
  const [status, setStatus] = useState<Status>("loading");
  const [playlist, setPlaylist] = useState<PlaylistDetail | null>(null);
  const [isOwner, setIsOwner] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getPlaylist(id, controller.signal)
      .then((p) => {
        setPlaylist(p);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setStatus(err instanceof ApiError && err.status === 404 ? "notfound" : "error");
      });
    return () => controller.abort();
  }, [id, reloadKey]);

  useEffect(() => {
    if (session !== "authed") return;
    const controller = new AbortController();
    api
      .getMyPlaylists(controller.signal)
      .then((res) => setIsOwner(res.playlists.some((p) => p.id === id)))
      .catch(() => {
        // Ownership is best-effort; without it the controls just stay hidden.
      });
    return () => controller.abort();
  }, [session, id]);

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  async function removeItem(videoId: string) {
    if (!playlist) return;
    const prev = playlist;
    setPlaylist({
      ...playlist,
      videos: playlist.videos.filter((v) => v.id !== videoId),
      video_count: Math.max(0, playlist.video_count - 1),
    });
    try {
      await api.removeFromPlaylist(id, videoId);
    } catch {
      setPlaylist(prev); // restore on failure
    }
  }

  async function deletePlaylist() {
    try {
      await api.deletePlaylist(id);
      router.push("/playlists");
    } catch {
      // Leave the page as-is on failure.
    }
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading playlist" />
      </div>
    );
  }
  if (status === "notfound") {
    return (
      <EmptyState
        title="Playlist not found"
        message="This playlist does not exist, or it is private."
      />
    );
  }
  if (status === "error" || playlist === null) {
    return <ErrorState message="Could not load this playlist." onRetry={retry} />;
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{playlist.title}</h1>
          {isOwner ? (
            <button
              type="button"
              onClick={() => void deletePlaylist()}
              className="shrink-0 rounded-full border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/40"
            >
              Delete playlist
            </button>
          ) : null}
        </div>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {playlist.video_count} {playlist.video_count === 1 ? "video" : "videos"} · {playlist.visibility}
        </p>
        {playlist.description ? (
          <p className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">
            {playlist.description}
          </p>
        ) : null}
      </header>

      {playlist.videos.length === 0 ? (
        <EmptyState
          title="This playlist is empty"
          message="Add videos to it from any watch page with “Save to playlist”."
        />
      ) : (
        <ul className="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {playlist.videos.map((video) => (
            <li key={video.id} className="flex flex-col gap-2">
              <VideoCard video={video} />
              {isOwner ? (
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => void removeItem(video.id)}
                    aria-label={`Remove ${video.title} from playlist`}
                    className="text-xs font-medium text-zinc-500 hover:text-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:hover:text-zinc-200"
                  >
                    Remove
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
