"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSession } from "@/components/auth/AuthProvider";

const TABS = [
  { href: "/moderation", label: "Reports" },
  { href: "/moderation/blocked", label: "Blocked videos" },
  { href: "/moderation/videos", label: "All videos" },
];

// ModerationTabs is the sub-navigation shared by the moderation surfaces (the
// report queue and the blocked-video list). It self-hides for anonymous/regular
// viewers so it never appears above a "Moderators only" gate.
export function ModerationTabs() {
  const { user } = useSession();
  const pathname = usePathname();

  if (user?.role !== "admin" && user?.role !== "moderator") return null;

  return (
    <nav className="mb-6 flex gap-2" aria-label="Moderation sections">
      {TABS.map((tab) => {
        const active = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={
              active
                ? "rounded-full bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "rounded-full border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
            }
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
