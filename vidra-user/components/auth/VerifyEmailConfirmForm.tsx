"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError, authApi } from "@/lib/api";

type State = "verifying" | "done" | "expired" | "error";

// Completes email verification: the user arrives from the verification link with
// a single-use token in the URL, which we submit automatically. On success we
// re-fetch the session (if signed in) so the "verify your email" prompt clears.
export function VerifyEmailConfirmForm({ token }: { token: string }) {
  const { status, reloadUser } = useSession();
  const [state, setState] = useState<State>(token ? "verifying" : "expired");
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true; // guard the double-invoke in React strict mode (dev)
    authApi
      .confirmEmailVerification({ token })
      .then(async () => {
        setState("done");
        // Best-effort: refresh the account so email_verified flips in the UI.
        // Harmless if signed out (me() 401 is swallowed).
        try {
          await reloadUser();
        } catch {
          // ignore — the verification itself already succeeded
        }
      })
      .catch((err) => {
        setState(err instanceof ApiError && err.status === 400 ? "expired" : "error");
      });
  }, [token, reloadUser]);

  if (state === "verifying") {
    return (
      <div className="flex items-center gap-3 py-4">
        <Spinner label="Verifying" />
        <p className="text-sm text-zinc-600 dark:text-zinc-400">Verifying your email…</p>
      </div>
    );
  }

  if (state === "done") {
    return (
      <div className="flex flex-col gap-4">
        <p
          role="status"
          className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-300"
        >
          Your email has been verified. Thanks!
        </p>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          <Link href="/" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
            Back to home
          </Link>
        </p>
      </div>
    );
  }

  // expired / invalid / unexpected error
  return (
    <div className="flex flex-col gap-4">
      <p
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
      >
        {state === "expired"
          ? "This verification link is invalid or has expired."
          : "Something went wrong verifying your email. Please try again."}
      </p>
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        {status === "authed" ? (
          <Link
            href="/settings"
            className="underline hover:text-zinc-700 dark:hover:text-zinc-200"
          >
            Resend the verification email
          </Link>
        ) : (
          <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
            Sign in
          </Link>
        )}
      </p>
    </div>
  );
}
