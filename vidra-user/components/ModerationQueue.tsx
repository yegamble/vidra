"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { Report, ReportStatus } from "@/lib/api";
import { relativeTime } from "@/lib/format";

const MAX_NOTE_LEN = 2000;

type Status = "loading" | "error" | "ready";

// ModerationQueue is the moderator/admin view of the abuse-report queue. A
// non-privileged or anonymous viewer is gated out (the session lives in memory,
// so a hard reload lands here signed out — we show a sign-in/permission prompt
// rather than fetching a 403). Privileged viewers see the queue + resolve actions.
export function ModerationQueue() {
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
            with a moderator account to review reports.
          </>
        }
      />
    );
  }

  return <Queue />;
}

function Queue() {
  const [status, setStatus] = useState<Status>("loading");
  const [reports, setReports] = useState<Report[]>([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getReports({ openOnly, limit: 100 }, controller.signal)
      .then((res) => {
        setReports(res.reports);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [openOnly, reloadKey]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }, []);

  // Switch filter (re-triggers the fetch effect). Set loading here rather than in
  // the effect body so a stale list doesn't flash before the refetch resolves.
  const selectFilter = useCallback(
    (next: boolean) => {
      if (next === openOnly) return;
      setStatus("loading");
      setOpenOnly(next);
    },
    [openOnly],
  );

  // After a resolve, update the row's status locally so it drops out of the
  // open-only view immediately; a later refetch confirms persistence.
  const onResolved = useCallback((id: string, newStatus: ReportStatus) => {
    setReports((prev) =>
      prev.map((r) => (r.id === id ? { ...r, status: newStatus } : r)),
    );
  }, []);

  const visible = openOnly ? reports.filter((r) => r.status === "open") : reports;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2" role="group" aria-label="Filter reports">
        <FilterButton active={openOnly} onClick={() => selectFilter(true)}>
          Open
        </FilterButton>
        <FilterButton active={!openOnly} onClick={() => selectFilter(false)}>
          All
        </FilterButton>
      </div>

      {status === "loading" ? (
        <div className="flex justify-center py-24">
          <Spinner label="Loading reports" />
        </div>
      ) : status === "error" ? (
        <ErrorState message="Could not load the moderation queue." onRetry={retry} />
      ) : visible.length === 0 ? (
        <EmptyState
          title={openOnly ? "No open reports" : "No reports yet"}
          message={
            openOnly
              ? "Nothing to review right now. Reports filed by viewers will appear here."
              : "When viewers report a video or comment, it shows up here."
          }
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {visible.map((report) => (
            <li key={report.id}>
              <ReportRow report={report} onResolved={onResolved} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={
        active
          ? "rounded-full bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
          : "rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      }
    >
      {children}
    </button>
  );
}

const STATUS_STYLE: Record<ReportStatus, string> = {
  open: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  accepted: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  rejected: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

type RowState = "idle" | "submitting";

function ReportRow({
  report,
  onResolved,
}: {
  report: Report;
  onResolved: (id: string, status: ReportStatus) => void;
}) {
  const [note, setNote] = useState("");
  const [rowState, setRowState] = useState<RowState>("idle");
  const [error, setError] = useState<string | null>(null);

  async function resolve(status: "accepted" | "rejected") {
    if (rowState === "submitting") return;
    setRowState("submitting");
    setError(null);
    try {
      await api.resolveReport(report.id, { status, note: note.trim() || undefined });
      onResolved(report.id, status);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resolve this report.");
      setRowState("idle");
    }
  }

  return (
    <article className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
        <span
          className={`rounded-full px-2 py-0.5 font-medium capitalize ${STATUS_STYLE[report.status]}`}
        >
          {report.status}
        </span>
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 font-medium text-zinc-600 capitalize dark:bg-zinc-800 dark:text-zinc-300">
          {report.target_type}
        </span>
        <span>
          by <span className="font-medium text-zinc-700 dark:text-zinc-200">{report.reporter.username}</span>
        </span>
        <span aria-hidden>·</span>
        <span>{relativeTime(report.created_at)}</span>
      </div>

      <ReportTarget report={report} />

      <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
        <span className="font-medium">Reason:</span> {report.reason}
      </p>

      {report.status !== "open" && report.moderator_note ? (
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          <span className="font-medium">Note:</span> {report.moderator_note}
        </p>
      ) : null}

      {report.status === "open" ? (
        <div className="mt-3 flex flex-col gap-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium text-zinc-600 dark:text-zinc-300">
              Internal note (optional)
            </span>
            <textarea
              aria-label="Internal moderator note"
              rows={2}
              maxLength={MAX_NOTE_LEN}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
          </label>
          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={rowState === "submitting"}
              onClick={() => void resolve("accepted")}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 disabled:opacity-60"
            >
              Accept
            </button>
            <button
              type="button"
              disabled={rowState === "submitting"}
              onClick={() => void resolve("rejected")}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              Reject
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

// ReportTarget shows the reported content: a link to the video for video reports,
// or the quoted comment body for comment reports.
function ReportTarget({ report }: { report: Report }) {
  if (report.target_type === "video" && report.video_id) {
    return (
      <p className="mt-2 text-sm">
        <Link
          href={`/videos/${report.video_id}`}
          className="font-medium text-zinc-900 underline hover:text-zinc-700 dark:text-zinc-100 dark:hover:text-zinc-300"
        >
          {report.video_title || "Untitled video"}
        </Link>
      </p>
    );
  }
  if (report.target_type === "comment") {
    return (
      <blockquote className="mt-2 border-l-2 border-zinc-300 pl-3 text-sm text-zinc-700 italic dark:border-zinc-700 dark:text-zinc-300">
        {report.comment_body || "(comment unavailable)"}
      </blockquote>
    );
  }
  return null;
}
