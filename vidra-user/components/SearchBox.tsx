"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// Header search box: submitting navigates to /search?q=… (the results page reads
// the query from the URL). Uncontrolled-by-URL on purpose so it works in the
// always-present header without forcing dynamic rendering.
export function SearchBox() {
  const router = useRouter();
  const [q, setQ] = useState("");

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        const query = q.trim();
        if (query) router.push(`/search?q=${encodeURIComponent(query)}`);
      }}
      className="w-full max-w-md"
    >
      <input
        type="search"
        name="q"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search videos"
        aria-label="Search videos"
        className="w-full rounded-md border border-zinc-300 px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
      />
    </form>
  );
}
