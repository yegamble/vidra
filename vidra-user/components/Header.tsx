import Link from "next/link";

import { AccountMenu } from "@/components/auth/AccountMenu";

// App shell header: brand + primary nav + account menu. Search lands in a later
// slice.
export function Header() {
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-black/80">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-6 px-4">
        <Link
          href="/"
          className="text-lg font-semibold tracking-tight focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500"
        >
          Vidra
        </Link>
        <nav className="flex items-center gap-4 text-sm text-zinc-600 dark:text-zinc-300">
          <Link href="/" className="hover:text-zinc-900 dark:hover:text-zinc-100">
            Home
          </Link>
        </nav>
        <div className="ml-auto">
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}
