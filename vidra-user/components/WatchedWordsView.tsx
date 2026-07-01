"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { WatchedWord } from "@/lib/api";
import { relativeTime } from "@/lib/format";

const MAX_WORD_LEN = 100;

type Status = "loading" | "error" | "ready";

// WatchedWordsView is the moderator/admin watched-words list: add and remove
// instance-wide watched terms. A non-privileged or anonymous viewer is gated out
// (the session lives in memory, so a hard reload lands here signed out — show a
// prompt rather than fetching a 403).
export function WatchedWordsView() {
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
            with a moderator account to manage watched words.
          </>
        }
      />
    );
  }

  return <WordsList />;
}

function WordsList() {
  const [status, setStatus] = useState<Status>("loading");
  const [words, setWords] = useState<WatchedWord[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getWatchedWords({ limit: 100 }, controller.signal)
      .then((res) => {
        setWords(res.words);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [reloadKey]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }, []);

  const onAdded = useCallback((word: WatchedWord) => {
    setWords((prev) => [word, ...prev]);
  }, []);

  const onRemoved = useCallback((id: string) => {
    setWords((prev) => prev.filter((w) => w.id !== id));
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <AddWordForm onAdded={onAdded} />

      {status === "loading" ? (
        <div className="flex justify-center py-16">
          <Spinner label="Loading watched words" />
        </div>
      ) : status === "error" ? (
        <ErrorState message="Could not load watched words." onRetry={retry} />
      ) : words.length === 0 ? (
        <EmptyState
          title="No watched words"
          message="Add a term above. Content containing a watched word can be flagged for review."
        />
      ) : (
        <ul className="flex flex-col gap-2">
          {words.map((w) => (
            <li key={w.id}>
              <WordRow word={w} onRemoved={onRemoved} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AddWordForm({ onAdded }: { onAdded: (word: WatchedWord) => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const word = value.trim();
    if (word === "" || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.addWatchedWord(word);
      onAdded(created);
      setValue("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("That word is already on the list.");
      } else {
        setError(err instanceof ApiError ? err.message : "Could not add this word.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="flex gap-2">
        <input
          type="text"
          aria-label="Add a watched word"
          placeholder="Add a watched word or phrase"
          maxLength={MAX_WORD_LEN}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-full max-w-sm rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
        />
        <button
          type="submit"
          disabled={busy || value.trim() === ""}
          className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {busy ? "Adding…" : "Add"}
        </button>
      </div>
      {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
    </form>
  );
}

function WordRow({ word, onRemoved }: { word: WatchedWord; onRemoved: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteWatchedWord(word.id);
      onRemoved(word.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove this word.");
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{word.word}</p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          added {relativeTime(word.created_at)}
          {word.created_by_username ? (
            <>
              {" "}by <span className="font-medium text-zinc-700 dark:text-zinc-200">{word.created_by_username}</span>
            </>
          ) : null}
        </p>
        {error ? <p className="mt-1 text-xs text-red-600 dark:text-red-400">{error}</p> : null}
      </div>
      <button
        type="button"
        disabled={busy}
        aria-label={`Remove ${word.word}`}
        onClick={() => void remove()}
        className="shrink-0 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      >
        Remove
      </button>
    </div>
  );
}
