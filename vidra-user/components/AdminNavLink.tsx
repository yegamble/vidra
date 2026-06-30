"use client";

import Link from "next/link";

import { useSession } from "@/components/auth/AuthProvider";

// AdminNavLink renders the Admin nav entry only for admins. The session lives in
// memory, so this is empty for anonymous/regular viewers and after a hard reload
// (until refresh-token rehydration lands).
export function AdminNavLink() {
  const { user } = useSession();
  if (user?.role !== "admin") return null;
  return (
    <Link href="/admin/users" className="hover:text-zinc-900 dark:hover:text-zinc-100">
      Admin
    </Link>
  );
}
