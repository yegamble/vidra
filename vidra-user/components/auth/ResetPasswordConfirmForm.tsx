"use client";

import Link from "next/link";
import { useState } from "react";

import { ApiError, authApi } from "@/lib/api";

// Completes a password reset: the user arrives from the reset email link with a
// single-use token in the URL, chooses a new password, and on success is sent to
// sign in (the backend revokes all existing sessions). An invalid/expired token
// (or a missing one) points the user back to request a fresh link.
export function ResetPasswordConfirmForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  async function submit() {
    setPasswordError(null);
    setFormError(null);
    setExpired(false);
    if (password !== confirm) {
      setPasswordError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await authApi.confirmPasswordReset({ token, password });
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setExpired(true);
      } else if (err instanceof ApiError && err.fields && err.fields.length > 0) {
        const pw = err.fields.find((f) => f.field === "password");
        setPasswordError(pw ? pw.message : err.message);
      } else if (err instanceof ApiError) {
        setFormError(err.message);
      } else {
        setFormError("Something went wrong. Please try again.");
      }
      setSubmitting(false);
    }
  }

  // No token in the link (or the backend rejected it as invalid/expired): send
  // the user back to request a fresh one.
  if (!token || expired) {
    return (
      <div className="flex flex-col gap-4">
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
        >
          This reset link is invalid or has expired.
        </p>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          <Link
            href="/reset-password"
            className="underline hover:text-zinc-700 dark:hover:text-zinc-200"
          >
            Request a new reset link
          </Link>
        </p>
      </div>
    );
  }

  if (done) {
    return (
      <div className="flex flex-col gap-4">
        <p
          role="status"
          className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-300"
        >
          Your password has been reset. You can now sign in with your new password.
        </p>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
            Sign in
          </Link>
        </p>
      </div>
    );
  }

  const inputClass =
    "rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900";

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="flex flex-col gap-4"
    >
      {formError ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
        >
          {formError}
        </p>
      ) : null}

      <div className="flex flex-col gap-1">
        <label htmlFor="reset-password" className="text-sm font-medium">
          New password
        </label>
        <input
          id="reset-password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-invalid={passwordError ? true : undefined}
          aria-describedby={passwordError ? "reset-password-error" : undefined}
          className={inputClass}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="reset-password-confirm" className="text-sm font-medium">
          Confirm new password
        </label>
        <input
          id="reset-password-confirm"
          name="confirm"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          aria-invalid={passwordError ? true : undefined}
          aria-describedby={passwordError ? "reset-password-error" : undefined}
          className={inputClass}
        />
        {passwordError ? (
          <p id="reset-password-error" className="text-xs text-red-600 dark:text-red-400">
            {passwordError}
          </p>
        ) : null}
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        {submitting ? "Resetting…" : "Reset password"}
      </button>
    </form>
  );
}
