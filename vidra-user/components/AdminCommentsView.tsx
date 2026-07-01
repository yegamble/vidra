"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { AdminComment } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "ready";

// AdminCommentsView is the moderator/admin comments overview: browse every
// comment and delete any of them. A non-privileged or anonymous viewer is gated
// out (the session lives in memory, so a hard reload lands here signed out — show
// a prompt rather than fetching a 403).
export function AdminCommentsView() {
  const { user } = useSession();
  const role = user?.role;

  if (role !== "admin" && role !== "moderator") {
    return (
      <EmptyState
        title="Moderators only"
        message={
          <>
            This page is for moderators and administrators.{" "}
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            with a moderator account to review comments.
          </>
        }
      />
    );
  }

  return <CommentsList />;
}

function CommentsList() {
  const [status, setStatus] = useState<Status>("loading");
  const [comments, setComments] = useState<AdminComment[]>([]);
  const [query, setQuery] = useState("");
  const [input, setInput] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getAdminComments({ q: query || undefined, limit: 100 }, controller.signal)
      .then((res) => {
        setComments(res.comments);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [query, reloadKey]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }, []);

  const submitSearch = useCallback(
    (next: string) => {
      if (next === query) return;
      setStatus("loading");
      setQuery(next);
    },
    [query],
  );

  // Drop a deleted comment from the list.
  const onDeleted = useCallback((id: string) => {
    setComments((prev) => prev.filter((c) => c.id !== id));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <form
        role="search"
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submitSearch(input.trim());
        }}
      >
        <input
          type="search"
          aria-label="Search comments"
          placeholder="Search by text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="w-full max-w-sm rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Search
        </button>
        {query ? (
          <button
            type="button"
            onClick={() => {
              setInput("");
              submitSearch("");
            }}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            Clear
          </button>
        ) : null}
      </form>

      {status === "loading" ? (
        <div className="flex justify-center py-24">
          <Spinner label="Loading comments" />
        </div>
      ) : status === "error" ? (
        <ErrorState message="Could not load comments." onRetry={retry} />
      ) : comments.length === 0 ? (
        <EmptyState
          title={query ? "No matching comments" : "No comments yet"}
          message={query ? "Try a different search term." : "Comments will appear here as viewers post them."}
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {comments.map((c) => (
            <li key={c.id}>
              <CommentRow comment={c} onDeleted={onDeleted} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CommentRow({
  comment,
  onDeleted,
}: {
  comment: AdminComment;
  onDeleted: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteComment(comment.id);
      onDeleted(comment.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete this comment.");
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="font-medium text-zinc-700 dark:text-zinc-200">
          {comment.author_display_name || comment.author_username}
        </span>
        <span aria-hidden>·</span>
        <span>{relativeTime(comment.created_at)}</span>
        <span aria-hidden>·</span>
        <span>
          on{" "}
          <Link
            href={`/videos/${comment.video_id}`}
            className="underline hover:text-zinc-700 dark:hover:text-zinc-200"
          >
            {comment.video_title || "a video"}
          </Link>
        </span>
      </div>

      <p className="mt-2 text-sm whitespace-pre-wrap text-zinc-800 dark:text-zinc-200">{comment.body}</p>

      {error ? <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p> : null}

      <div className="mt-3 flex items-center gap-2">
        {confirming ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => void remove()}
              className="rounded-md bg-red-600 px-3 py-1 text-sm font-medium text-white hover:bg-red-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-60"
            >
              {busy ? "Deleting…" : "Confirm delete"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming(false)}
              className="rounded-md border border-zinc-300 px-3 py-1 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="rounded-md border border-red-300 px-3 py-1 text-sm font-medium text-red-700 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40"
          >
            Delete
          </button>
        )}
      </div>
    </article>
  );
}
