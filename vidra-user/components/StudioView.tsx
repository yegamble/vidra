"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { Channel, Video, VideoPrivacy, VideoState } from "@/lib/api";

type Status = "loading" | "error" | "ready";

// StudioView is the creator surface: create a channel, then upload a video to it.
// The session lives in memory, so a hard reload lands here signed out.
export function StudioView() {
  const { status } = useSession();

  if (status !== "authed") {
    return (
      <EmptyState
        title="Sign in to use the studio"
        message={
          <>
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to create a channel and publish videos.
          </>
        }
      />
    );
  }

  return <Studio />;
}

function Studio() {
  const [status, setStatus] = useState<Status>("loading");
  const [channels, setChannels] = useState<Channel[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getMyChannels(controller.signal)
      .then((res) => {
        setChannels(res.channels);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [reloadKey]);

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading your studio" />
      </div>
    );
  }
  if (status === "error") {
    return (
      <ErrorState
        message="Could not load your studio."
        onRetry={() => {
          setStatus("loading");
          setReloadKey((k) => k + 1);
        }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <ChannelSection
        channels={channels}
        onCreated={(ch) => setChannels((list) => [ch, ...list])}
      />
      {channels.length > 0 ? <UploadSection channels={channels} /> : null}
      {channels.length > 0 ? <MyVideosSection channels={channels} /> : null}
    </div>
  );
}

function ChannelSection({
  channels,
  onCreated,
}: {
  channels: Channel[];
  onCreated: (ch: Channel) => void;
}) {
  const [handle, setHandle] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (busy || handle.trim() === "" || displayName.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      const ch = await api.createChannel({ handle: handle.trim(), display_name: displayName.trim() });
      onCreated(ch);
      setHandle("");
      setDisplayName("");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "That handle is already taken."
          : "Could not create the channel.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Your channels</h2>
      {channels.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Create your first channel to start publishing.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {channels.map((ch) => (
            <li key={ch.id}>
              <Link
                href={`/channels/${ch.handle}`}
                className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:hover:bg-zinc-900/40"
              >
                <span className="min-w-0 flex-1 truncate font-medium">{ch.display_name}</span>
                <span className="shrink-0 text-xs text-zinc-500 dark:text-zinc-400">@{ch.handle}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <form
        onSubmit={(e) => void create(e)}
        className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 sm:flex-row sm:items-end dark:border-zinc-800"
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Handle</span>
          <input
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="ada_makes"
            aria-label="Channel handle"
            minLength={3}
            maxLength={30}
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">Display name</span>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Ada Makes"
            aria-label="Channel display name"
            maxLength={50}
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <button
          type="submit"
          disabled={busy || handle.trim() === "" || displayName.trim() === ""}
          className="rounded-full bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Create channel
        </button>
      </form>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </section>
  );
}

type UploadState = "idle" | "uploading" | "done" | "error";

function UploadSection({ channels }: { channels: Channel[] }) {
  const [handle, setHandle] = useState(channels[0]?.handle ?? "");
  const [title, setTitle] = useState("");
  const [privacy, setPrivacy] = useState<VideoPrivacy>("public");
  const [state, setState] = useState<UploadState>("idle");
  const [published, setPublished] = useState<Video | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (state === "uploading" || title.trim() === "" || !file || handle === "") return;
    setState("uploading");
    setError(null);
    setPublished(null);
    try {
      const draft = await api.createVideoDraft(handle, { title: title.trim(), privacy });
      const res = await api.uploadVideoFile(draft.id, file);
      setPublished(res.video);
      setState("done");
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 415
          ? "That file type is not a supported video."
          : "Upload failed. Please try again.",
      );
      setState("error");
    }
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Upload a video</h2>
      <form
        onSubmit={(e) => void upload(e)}
        className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
      >
        {channels.length > 1 ? (
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Channel</span>
            <select
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              aria-label="Channel"
              className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
            >
              {channels.map((ch) => (
                <option key={ch.id} value={ch.handle}>
                  {ch.display_name} (@{ch.handle})
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="My video"
            aria-label="Video title"
            maxLength={200}
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Privacy</span>
          <select
            value={privacy}
            onChange={(e) => setPrivacy(e.target.value as VideoPrivacy)}
            aria-label="Privacy"
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          >
            <option value="public">Public</option>
            <option value="unlisted">Unlisted</option>
            <option value="private">Private</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Video file</span>
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            aria-label="Video file"
            className="text-sm file:mr-3 file:rounded file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-sm file:font-medium dark:file:bg-zinc-800"
          />
        </label>
        <div>
          <button
            type="submit"
            disabled={state === "uploading"}
            className="rounded-full bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {state === "uploading" ? "Uploading…" : "Publish"}
          </button>
        </div>
      </form>
      {state === "done" && published ? (
        <p className="text-sm text-green-700 dark:text-green-400">
          Published!{" "}
          <Link href={`/videos/${published.id}`} className="font-medium underline">
            View “{published.title}”
          </Link>
        </p>
      ) : null}
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </section>
  );
}

// MyVideosSection lists the owner's videos for the selected channel (the owner
// view returns drafts/private too) and lets them edit metadata or delete a video.
// It refetches on a remount/channel change; after an edit/delete the local list
// is updated from the server result.
function MyVideosSection({ channels }: { channels: Channel[] }) {
  const [handle, setHandle] = useState(channels[0]?.handle ?? "");
  const [status, setStatus] = useState<Status>("loading");
  const [videos, setVideos] = useState<Video[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (handle === "") return;
    const controller = new AbortController();
    api
      .listChannelVideos(handle, undefined, controller.signal)
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
  }, [handle, reloadKey]);

  function refetch() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Your videos</h2>
        <button
          type="button"
          onClick={refetch}
          className="rounded-full border border-zinc-300 px-3 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          Refresh
        </button>
      </div>

      {channels.length > 1 ? (
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Channel</span>
          <select
            value={handle}
            onChange={(e) => {
              setStatus("loading");
              setHandle(e.target.value);
            }}
            aria-label="Videos channel"
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          >
            {channels.map((ch) => (
              <option key={ch.id} value={ch.handle}>
                {ch.display_name} (@{ch.handle})
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {status === "loading" ? (
        <div className="flex justify-center py-8">
          <Spinner label="Loading your videos" />
        </div>
      ) : status === "error" ? (
        <ErrorState message="Could not load your videos." onRetry={refetch} />
      ) : videos.length === 0 ? (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">No videos in this channel yet.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
          {videos.map((v) => (
            <VideoRow
              key={v.id}
              video={v}
              onUpdated={(u) => setVideos((list) => list.map((x) => (x.id === u.id ? u : x)))}
              onDeleted={() => setVideos((list) => list.filter((x) => x.id !== v.id))}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

type RowMode = "view" | "edit" | "confirm-delete";

// VideoRow shows one of the owner's videos with inline edit (title + privacy) and
// a two-step delete confirmation. The server result is the source of truth.
function VideoRow({
  video,
  onUpdated,
  onDeleted,
}: {
  video: Video;
  onUpdated: (v: Video) => void;
  onDeleted: () => void;
}) {
  const [mode, setMode] = useState<RowMode>("view");
  const [title, setTitle] = useState(video.title);
  const [privacy, setPrivacy] = useState<VideoPrivacy>(video.privacy);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (busy || title.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateVideo(video.id, { title: title.trim(), privacy });
      onUpdated(updated);
      setMode("view");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the video.");
    } finally {
      setBusy(false);
    }
  }

  function cancelEdit() {
    setMode("view");
    setTitle(video.title);
    setPrivacy(video.privacy);
    setError(null);
  }

  async function remove() {
    setBusy(true);
    try {
      await api.deleteVideo(video.id);
      onDeleted();
    } catch {
      setBusy(false);
      setMode("view");
    }
  }

  if (mode === "edit") {
    return (
      <li className="flex flex-col gap-2 px-4 py-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="Edit title"
            maxLength={200}
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Privacy</span>
          <select
            value={privacy}
            onChange={(e) => setPrivacy(e.target.value as VideoPrivacy)}
            aria-label="Edit privacy"
            className="rounded border border-zinc-300 px-3 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          >
            <option value="public">Public</option>
            <option value="unlisted">Unlisted</option>
            <option value="private">Private</option>
          </select>
        </label>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || title.trim() === ""}
            onClick={() => void save()}
            className="rounded-full bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            Save
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={cancelEdit}
            className="rounded-full border border-zinc-300 px-4 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
        </div>
      </li>
    );
  }

  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">
          <Link href={`/videos/${video.id}`} className="hover:underline">
            {video.title}
          </Link>
        </p>
        <div className="mt-1 flex items-center gap-2 text-xs">
          <StateBadge state={video.state} />
          <span className="text-zinc-500 dark:text-zinc-400">{privacyLabel(video.privacy)}</span>
        </div>
      </div>
      {mode === "confirm-delete" ? (
        <div className="flex shrink-0 items-center gap-2 text-sm">
          <span className="text-zinc-600 dark:text-zinc-300">Delete?</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => void remove()}
            className="font-medium text-red-600 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:text-red-400"
          >
            Confirm
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setMode("view")}
            className="font-medium text-zinc-500 hover:text-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:text-zinc-400 dark:hover:text-zinc-200"
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex shrink-0 items-center gap-2 text-sm">
          <button
            type="button"
            onClick={() => setMode("edit")}
            className="font-medium text-zinc-600 hover:text-zinc-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:text-zinc-300 dark:hover:text-zinc-100"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => setMode("confirm-delete")}
            className="font-medium text-zinc-500 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:text-zinc-400 dark:hover:text-red-400"
          >
            Delete
          </button>
        </div>
      )}
    </li>
  );
}

function privacyLabel(p: VideoPrivacy): string {
  return p === "public" ? "Public" : p === "unlisted" ? "Unlisted" : "Private";
}

function StateBadge({ state }: { state: VideoState }) {
  const styles: Record<VideoState, string> = {
    draft: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
    processing: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
    published: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200",
    failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 font-medium capitalize ${styles[state]}`}>{state}</span>
  );
}
