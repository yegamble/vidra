"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ApiError, authApi } from "@/lib/api";
import type { UpdateProfileRequest } from "@/lib/api";

// SettingsView lets the signed-in user edit their profile (display name, bio)
// and deactivate their account. The session lives in memory, so a hard reload
// lands here signed out — we show a sign-in prompt rather than an empty form.
export function SettingsView() {
  const { status, user, updateProfile, deactivate } = useSession();

  if (status === "anon" || !user) {
    return (
      <EmptyState
        title="Sign in to manage your account"
        message={
          <>
            Your session has ended.{" "}
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to edit your profile.
          </>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1 border-b border-zinc-200 pb-4 dark:border-zinc-800">
        <h1 className="text-2xl font-semibold tracking-tight">Account settings</h1>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Signed in as @{user.username}
        </p>
      </header>
      {user.email_verified ? null : <EmailVerificationSection email={user.email} />}
      <ProfileForm
        key={user.id}
        initialDisplayName={user.display_name}
        initialBio={user.bio}
        updateProfile={updateProfile}
      />
      <section className="flex items-center justify-between gap-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
        <div>
          <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">Muted accounts</h2>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Accounts whose comments are hidden from you.
          </p>
        </div>
        <Link
          href="/settings/mutes"
          className="shrink-0 rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          Manage
        </Link>
      </section>
      <DeactivateSection deactivate={deactivate} />
    </div>
  );
}

function EmailVerificationSection({ email }: { email: string }) {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  async function resend() {
    setError(null);
    setState("sending");
    try {
      await authApi.requestEmailVerification();
      setState("sent");
    } catch (err) {
      setState("idle");
      setError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again.",
      );
    }
  }

  return (
    <section className="flex max-w-xl flex-col gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 dark:border-amber-900/50 dark:bg-amber-950/20">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-amber-800 dark:text-amber-300">
          Verify your email
        </h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Your email <span className="font-medium">{email}</span> is not verified yet. Check your
          inbox for the verification link, or resend it below.
        </p>
      </div>
      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
        >
          {error}
        </p>
      ) : null}
      {state === "sent" ? (
        <p
          role="status"
          className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-300"
        >
          Verification email sent. Check your inbox.
        </p>
      ) : (
        <button
          type="button"
          onClick={() => void resend()}
          disabled={state === "sending"}
          className="self-start rounded-md border border-amber-400 bg-white px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:opacity-60 dark:bg-transparent dark:text-amber-200 dark:hover:bg-amber-900/30"
        >
          {state === "sending" ? "Sending…" : "Resend verification email"}
        </button>
      )}
    </section>
  );
}

function DeactivateSection({ deactivate }: { deactivate: (password: string) => Promise<void> }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    setError(null);
    setSubmitting(true);
    try {
      await deactivate(password);
      // The account is disabled and the session is cleared; leave the page.
      router.push("/");
    } catch (err) {
      setSubmitting(false);
      if (err instanceof ApiError) {
        setError(err.status === 403 ? "Incorrect password." : err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    }
  }

  return (
    <section className="flex max-w-xl flex-col gap-3 rounded-md border border-red-200 p-4 dark:border-red-900/50">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-red-700 dark:text-red-300">Deactivate account</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          This disables your account and signs you out everywhere. You will not be able to sign in
          again. Confirm your password to continue.
        </p>
      </div>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-3"
      >
        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
          >
            {error}
          </p>
        ) : null}
        <div className="flex flex-col gap-1">
          <label htmlFor="deactivate-password" className="text-sm font-medium">
            Current password
          </label>
          <input
            id="deactivate-password"
            name="deactivate-password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </div>
        <button
          type="submit"
          disabled={submitting || password === ""}
          className="self-start rounded-md bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-60"
        >
          {submitting ? "Deactivating…" : "Deactivate account"}
        </button>
      </form>
    </section>
  );
}

function ProfileForm({
  initialDisplayName,
  initialBio,
  updateProfile,
}: {
  initialDisplayName: string;
  initialBio: string;
  updateProfile: (input: UpdateProfileRequest) => Promise<void>;
}) {
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [bio, setBio] = useState(initialBio);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");

  async function submit() {
    setFieldErrors({});
    setFormError(null);
    setState("saving");
    try {
      await updateProfile({ display_name: displayName, bio });
      setState("saved");
    } catch (err) {
      setState("idle");
      if (err instanceof ApiError && err.fields && err.fields.length > 0) {
        const map: Record<string, string> = {};
        for (const f of err.fields) map[f.field] = f.message;
        setFieldErrors(map);
      } else if (err instanceof ApiError) {
        setFormError(err.message);
      } else {
        setFormError("Something went wrong. Please try again.");
      }
    }
  }

  function edited(setter: (v: string) => void) {
    return (v: string) => {
      setter(v);
      setState("idle");
    };
  }

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="flex max-w-xl flex-col gap-4"
    >
      {formError ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300"
        >
          {formError}
        </p>
      ) : null}
      {state === "saved" ? (
        <p
          role="status"
          className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-300"
        >
          Profile saved.
        </p>
      ) : null}

      <div className="flex flex-col gap-1">
        <label htmlFor="settings-display-name" className="text-sm font-medium">
          Display name
        </label>
        <input
          id="settings-display-name"
          name="settings-display-name"
          type="text"
          maxLength={50}
          value={displayName}
          onChange={(e) => edited(setDisplayName)(e.target.value)}
          aria-invalid={fieldErrors.display_name ? true : undefined}
          aria-describedby={fieldErrors.display_name ? "settings-display-name-error" : undefined}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        {fieldErrors.display_name ? (
          <p id="settings-display-name-error" className="text-xs text-red-600 dark:text-red-400">
            {fieldErrors.display_name}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="settings-bio" className="text-sm font-medium">
          Bio
        </label>
        <textarea
          id="settings-bio"
          name="settings-bio"
          rows={4}
          maxLength={1000}
          value={bio}
          onChange={(e) => edited(setBio)(e.target.value)}
          aria-invalid={fieldErrors.bio ? true : undefined}
          aria-describedby={fieldErrors.bio ? "settings-bio-error" : undefined}
          className="resize-y rounded-md border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
        />
        {fieldErrors.bio ? (
          <p id="settings-bio-error" className="text-xs text-red-600 dark:text-red-400">
            {fieldErrors.bio}
          </p>
        ) : null}
      </div>

      <button
        type="submit"
        disabled={state === "saving"}
        className="self-start rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
      >
        {state === "saving" ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
