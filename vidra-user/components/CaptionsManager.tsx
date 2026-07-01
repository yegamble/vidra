"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api";
import type { Caption } from "@/lib/api";

// CaptionsManager lists a video's WebVTT caption tracks and lets the owner upload
// (or replace) and remove them. Embedded in the studio's per-video edit surface.
export function CaptionsManager({ videoId }: { videoId: string }) {
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [language, setLanguage] = useState("");
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getCaptions(videoId, controller.signal)
      .then((res) => {
        setCaptions(res.captions);
        setLoaded(true);
      })
      .catch(() => {
        if (!controller.signal.aborted) setLoaded(true);
      });
    return () => controller.abort();
  }, [videoId]);

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !file || language.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.uploadCaption(videoId, {
        language: language.trim(),
        label: label.trim() || undefined,
        file,
      });
      // Replace-or-add by language, keeping the list sorted.
      setCaptions((prev) =>
        [...prev.filter((c) => c.language !== created.language), created].sort((a, b) =>
          a.language.localeCompare(b.language),
        ),
      );
      setLanguage("");
      setLabel("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError("The file must be WebVTT and the language a valid tag (e.g. en, pt-BR).");
      } else {
        setError(err instanceof ApiError ? err.message : "Could not upload the caption.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function remove(lang: string) {
    try {
      await api.deleteCaption(videoId, lang);
      setCaptions((prev) => prev.filter((c) => c.language !== lang));
    } catch {
      // Leave the caption in place on failure.
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <p className="text-sm font-medium">Captions</p>

      {captions.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {captions.map((c) => (
            <li key={c.language} className="flex items-center justify-between gap-2 text-sm">
              <span>
                <span className="font-medium">{c.language}</span>
                {c.label ? <span className="text-zinc-500 dark:text-zinc-400"> · {c.label}</span> : null}
              </span>
              <button
                type="button"
                aria-label={`Remove ${c.language} caption`}
                onClick={() => void remove(c.language)}
                className="text-xs font-medium text-zinc-500 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:text-zinc-400 dark:hover:text-red-400"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : loaded ? (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">No captions yet.</p>
      ) : null}

      <form className="flex flex-col gap-2" onSubmit={upload}>
        <div className="flex flex-wrap gap-2">
          <input
            aria-label="Caption language"
            placeholder="Language (e.g. en)"
            value={language}
            maxLength={35}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-28 rounded border border-zinc-300 px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <input
            aria-label="Caption label"
            placeholder="Label (optional)"
            value={label}
            maxLength={100}
            onChange={(e) => setLabel(e.target.value)}
            className="w-40 rounded border border-zinc-300 px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <input
            ref={fileRef}
            type="file"
            aria-label="Caption file"
            accept=".vtt,text/vtt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm"
          />
          <button
            type="submit"
            disabled={busy || !file || language.trim() === ""}
            className="rounded-full bg-zinc-900 px-3 py-1 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
        {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      </form>
    </div>
  );
}
