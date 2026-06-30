"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { ApiError, api } from "@/lib/api";

const MAX_REASON_LEN = 2000;

export type ReportKind = "video" | "comment";

// ReportButton lets an authenticated viewer file an abuse report against a video
// or a comment. Anonymous viewers get a sign-in link instead. Clicking opens an
// accessible modal with a required reason; on success it confirms and the backend
// treats repeat reports idempotently.
export function ReportButton({
  kind,
  targetId,
  variant = "pill",
}: {
  kind: ReportKind;
  targetId: string;
  variant?: "pill" | "link";
}) {
  const { status } = useSession();
  const [open, setOpen] = useState(false);

  if (status !== "authed") {
    return (
      <Link
        href="/login"
        className={
          variant === "pill"
            ? "rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
            : "text-xs font-medium text-zinc-500 hover:text-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:text-zinc-400 dark:hover:text-zinc-200"
        }
      >
        Sign in to report
      </Link>
    );
  }

  return (
    <>
      <button
        type="button"
        aria-label={`Report this ${kind}`}
        onClick={() => setOpen(true)}
        className={
          variant === "pill"
            ? "flex items-center gap-1.5 rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
            : "text-xs font-medium text-zinc-500 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:text-zinc-400 dark:hover:text-red-400"
        }
      >
        {variant === "pill" ? <span aria-hidden>⚑</span> : null}
        <span>Report</span>
      </button>
      {open ? (
        <ReportDialog kind={kind} targetId={targetId} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

type DialogState = "idle" | "submitting" | "done";

function ReportDialog({
  kind,
  targetId,
  onClose,
}: {
  kind: ReportKind;
  targetId: string;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [state, setState] = useState<DialogState>("idle");
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Focus the reason field on open and close on Escape.
  useEffect(() => {
    textareaRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit() {
    const trimmed = reason.trim();
    if (trimmed === "" || state === "submitting") return;
    setState("submitting");
    setError(null);
    try {
      if (kind === "video") {
        await api.reportVideo(targetId, trimmed);
      } else {
        await api.reportComment(targetId, trimmed);
      }
      setState("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit your report.");
      setState("idle");
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Report this ${kind}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-md rounded-lg border border-zinc-200 bg-white p-5 shadow-xl dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-base font-semibold tracking-tight">
          Report this {kind}
        </h2>

        {state === "done" ? (
          <div className="mt-3 flex flex-col gap-4">
            <p className="text-sm text-zinc-700 dark:text-zinc-300">
              Thanks — your report has been sent to the moderators.
            </p>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <form
            className="mt-3 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Reason</span>
              <textarea
                ref={textareaRef}
                aria-label="Reason for report"
                placeholder="Why are you reporting this?"
                rows={4}
                maxLength={MAX_REASON_LEN}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
              />
            </label>
            {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={state === "submitting" || reason.trim() === ""}
                className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
              >
                Submit report
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
