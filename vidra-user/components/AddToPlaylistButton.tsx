"use client";

import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { api } from "@/lib/api";
import type { Playlist } from "@/lib/api";

// AddToPlaylistButton lets a signed-in viewer add the current video to one of
// their playlists (or a new one) from the watch page. The playlist list loads
// the first time the menu opens.
export function AddToPlaylistButton({ videoId }: { videoId: string }) {
  const { status } = useSession();
  const [open, setOpen] = useState(false);
  const [playlists, setPlaylists] = useState<Playlist[] | null>(null); // null = not loaded
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);

  if (status !== "authed") {
    return (
      <Link
        href="/login"
        className="rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      >
        Sign in to save to a playlist
      </Link>
    );
  }

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && playlists === null) {
      try {
        const res = await api.getMyPlaylists();
        setPlaylists(res.playlists);
      } catch {
        setPlaylists([]);
      }
    }
  }

  function markAdded(plId: string) {
    setAdded((s) => {
      const next = new Set(s);
      next.add(plId);
      return next;
    });
  }

  async function add(plId: string) {
    if (busy) return;
    setBusy(plId);
    try {
      await api.addToPlaylist(plId, videoId);
      markAdded(plId);
    } catch {
      // Leave unchanged on failure.
    } finally {
      setBusy(null);
    }
  }

  async function createAndAdd(e: React.FormEvent) {
    e.preventDefault();
    const t = newTitle.trim();
    if (creating || t === "") return;
    setCreating(true);
    try {
      const pl = await api.createPlaylist({ title: t });
      await api.addToPlaylist(pl.id, videoId);
      setPlaylists((list) => [pl, ...(list ?? [])]);
      markAdded(pl.id);
      setNewTitle("");
    } catch {
      // Leave unchanged on failure.
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => void toggle()}
        className="flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      >
        <span aria-hidden>＋</span>
        <span>Save to playlist</span>
      </button>
      {open ? (
        <div className="absolute left-0 z-20 mt-2 w-64 rounded-lg border border-zinc-200 bg-white p-2 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
          {playlists === null ? (
            <p className="px-2 py-1.5 text-sm text-zinc-500">Loading…</p>
          ) : playlists.length === 0 ? (
            <p className="px-2 py-1.5 text-sm text-zinc-500">No playlists yet — create one below.</p>
          ) : (
            <ul className="max-h-56 overflow-auto">
              {playlists.map((pl) => (
                <li key={pl.id}>
                  <button
                    type="button"
                    onClick={() => void add(pl.id)}
                    disabled={busy === pl.id}
                    aria-pressed={added.has(pl.id)}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:hover:bg-zinc-800"
                  >
                    <span aria-hidden className="w-4">
                      {added.has(pl.id) ? "✓" : ""}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{pl.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form
            onSubmit={(e) => void createAndAdd(e)}
            className="mt-2 flex items-center gap-2 border-t border-zinc-200 pt-2 dark:border-zinc-800"
          >
            <input
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="New playlist"
              aria-label="New playlist name"
              maxLength={200}
              className="min-w-0 flex-1 rounded border border-zinc-300 px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
            />
            <button
              type="submit"
              disabled={creating || newTitle.trim() === ""}
              className="shrink-0 rounded bg-zinc-900 px-2.5 py-1 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
            >
              Create
            </button>
          </form>
        </div>
      ) : null}
    </div>
  );
}
