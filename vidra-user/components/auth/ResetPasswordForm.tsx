"use client";

import Link from "next/link";
import { useState } from "react";

import { ApiError, authApi } from "@/lib/api";

// Requests a password-reset link. The backend always answers 202 (it never
// reveals whether the email belongs to an account), so on success we show the
// same neutral confirmation regardless — keeping the flow enumeration-safe.
export function ResetPasswordForm() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await authApi.requestPasswordReset({ email });
      setSent(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 422
            ? "Enter a valid email address."
            : err.message
          : "Something went wrong. Please try again.",
      );
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <div className="flex flex-col gap-4">
        <p
          role="status"
          className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-300"
        >
          If an account exists for that email, we&apos;ve sent a link to reset your
          password. Check your inbox.
        </p>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
            Back to sign in
          </Link>
        </p>
      </div>
    );
  }

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="flex flex-col gap-4"
    >
      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
        >
          {error}
        </p>
      ) : null}

      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Enter your account email and we&apos;ll send you a link to reset your password.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="reset-email" className="text-sm font-medium">
          Email
        </label>
        <input
          id="reset-email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        {submitting ? "Sending…" : "Send reset link"}
      </button>

      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        Remembered it?{" "}
        <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
          Back to sign in
        </Link>
      </p>
    </form>
  );
}
