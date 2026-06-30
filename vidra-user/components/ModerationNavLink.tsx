"use client";

import Link from "next/link";

import { useSession } from "@/components/auth/AuthProvider";

// ModerationNavLink renders the Moderation nav entry only for moderators/admins.
// The session lives in memory, so this is empty for anonymous/regular viewers and
// after a hard reload (until refresh-token rehydration lands).
export function ModerationNavLink() {
  const { user } = useSession();
  if (user?.role !== "admin" && user?.role !== "moderator") return null;
  return (
    <Link href="/moderation" className="hover:text-zinc-900 dark:hover:text-zinc-100">
      Moderation
    </Link>
  );
}
