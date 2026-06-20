"use client";

import Link from "next/link";

import { useSession } from "@/components/auth/AuthProvider";

// AccountMenu reflects session state in the header: a sign-in link when anon, or
// the username + sign-out when authenticated.
export function AccountMenu() {
  const { status, user, logout } = useSession();

  if (status === "authed" && user) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <span className="font-medium text-zinc-700 dark:text-zinc-200">{user.username}</span>
        <button
          type="button"
          onClick={() => {
            void logout();
          }}
          className="rounded-md border border-zinc-300 px-2.5 py-1 text-zinc-600 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <Link
      href="/login"
      className="rounded-md border border-zinc-300 px-2.5 py-1 text-sm text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
    >
      Sign in
    </Link>
  );
}
