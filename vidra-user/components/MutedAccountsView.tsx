"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, api } from "@/lib/api";
import type { MutedAccount } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "ready";

// MutedAccountsView lists the accounts the signed-in user has muted and lets them
// unmute. The session lives in memory, so a hard reload lands here signed out — we
// show a sign-in prompt rather than fetching a 401.
export function MutedAccountsView() {
  const { status, user } = useSession();

  if (status === "anon" || !user) {
    return (
      <EmptyState
        title="Sign in to manage muted accounts"
        message={
          <>
            Your session has ended.{" "}
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to see the accounts you have muted.
          </>
        }
      />
    );
  }

  return <MuteList />;
}

function MuteList() {
  const [status, setStatus] = useState<Status>("loading");
  const [accounts, setAccounts] = useState<MutedAccount[]>([]);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getMutedAccounts({ limit: 100 }, controller.signal)
      .then((res) => {
        setAccounts(res.accounts);
        setStatus("ready");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [reloadKey]);

  const retry = useCallback(() => {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }, []);

  const onUnmuted = useCallback((id: string) => {
    setAccounts((prev) => prev.filter((a) => a.user_id !== id));
  }, []);

  if (status === "loading") {
    return (
      <div className="flex justify-center py-16">
        <Spinner label="Loading muted accounts" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Could not load your muted accounts." onRetry={retry} />;
  }
  if (accounts.length === 0) {
    return (
      <EmptyState
        title="No muted accounts"
        message="When you mute an account its comments are hidden from you. Muted accounts appear here."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {accounts.map((account) => (
        <li key={account.user_id}>
          <MutedRow account={account} onUnmuted={onUnmuted} />
        </li>
      ))}
    </ul>
  );
}

function MutedRow({
  account,
  onUnmuted,
}: {
  account: MutedAccount;
  onUnmuted: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function unmute() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.unmuteAccount(account.user_id);
      onUnmuted(account.user_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not unmute this account.");
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">
          {account.display_name || account.username}
        </p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          @{account.username} · muted {relativeTime(account.muted_at)}
        </p>
        {error ? <p className="mt-1 text-xs text-red-600 dark:text-red-400">{error}</p> : null}
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={() => void unmute()}
        className="shrink-0 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
      >
        Unmute
      </button>
    </div>
  );
}
