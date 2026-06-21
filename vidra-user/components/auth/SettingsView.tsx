"use client";

import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ApiError } from "@/lib/api";
import type { UpdateProfileRequest } from "@/lib/api";

// SettingsView lets the signed-in user edit their profile (display name, bio).
// The session lives in memory, so a hard reload lands here signed out — we show
// a sign-in prompt rather than an empty form in that case.
export function SettingsView() {
  const { status, user, updateProfile } = useSession();

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
      <ProfileForm
        key={user.id}
        initialDisplayName={user.display_name}
        initialBio={user.bio}
        updateProfile={updateProfile}
      />
    </div>
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
