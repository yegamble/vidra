import Link from "next/link";

import { AccountMenu } from "@/components/auth/AccountMenu";
import { ModerationNavLink } from "@/components/ModerationNavLink";
import { NotificationsBell } from "@/components/NotificationsBell";
import { SearchBox } from "@/components/SearchBox";

// App shell header: brand + primary nav + search + account menu.
export function Header() {
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-black/80">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-4 px-4">
        <Link
          href="/"
          className="text-lg font-semibold tracking-tight focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500"
        >
          Vidra
        </Link>
        <nav className="hidden items-center gap-4 text-sm text-zinc-600 sm:flex dark:text-zinc-300">
          <Link href="/" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Home
          </Link>
          <Link href="/subscriptions" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Subscriptions
          </Link>
          <Link href="/library" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Library
          </Link>
          <Link href="/playlists" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Playlists
          </Link>
          <Link href="/history" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            History
          </Link>
          <Link href="/studio" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Studio
          </Link>
          <ModerationNavLink />
        </nav>
        <div className="flex flex-1 justify-center px-2">
          <SearchBox />
        </div>
        <NotificationsBell />
        <AccountMenu />
      </div>
    </header>
  );
}
