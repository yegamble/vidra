"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/AuthProvider";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type Status = "loading" | "error" | "ready";

// describe renders a notification as a human message plus the link to its target.
function describe(n: Notification): { text: string; href: string } {
  const actor = n.actor?.display_name || n.actor?.username || "Someone";
  if (n.type === "comment") {
    return {
      text: `${actor} commented on ${n.video_title || "your video"}`,
      href: n.video_id ? `/videos/${n.video_id}` : "#",
    };
  }
  // follow
  const channel = n.channel_display_name || n.channel_handle || "your channel";
  return {
    text: `${actor} started following ${channel}`,
    href: n.channel_handle ? `/channels/${n.channel_handle}` : "#",
  };
}

// NotificationsView shows the signed-in user's notifications with per-item and
// bulk "mark read" controls. The session lives in memory, so a hard reload lands
// here signed out — we prompt to sign in.
export function NotificationsView() {
  const { status } = useSession();

  if (status !== "authed") {
    return (
      <EmptyState
        title="Sign in to see your notifications"
        message={
          <>
            <Link href="/login" className="underline hover:text-zinc-700 dark:hover:text-zinc-200">
              Sign in
            </Link>{" "}
            to see when people follow your channel or comment on your videos.
          </>
        }
      />
    );
  }

  return <Notifications />;
}

function Notifications() {
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getNotifications({}, controller.signal)
      .then((res) => {
        setItems(res.notifications);
        setUnread(res.unread_count);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        void err;
        if (controller.signal.aborted) return;
        setStatus("error");
      });
    return () => controller.abort();
  }, [reloadKey]);

  function retry() {
    setStatus("loading");
    setReloadKey((k) => k + 1);
  }

  async function markRead(id: string) {
    const target = items.find((i) => i.id === id);
    if (!target || target.read) return;
    setItems((list) => list.map((i) => (i.id === id ? { ...i, read: true } : i))); // optimistic
    setUnread((n) => Math.max(0, n - 1));
    try {
      await api.markNotificationRead(id);
    } catch {
      setReloadKey((k) => k + 1); // resync on failure
    }
  }

  async function markAll() {
    if (unread === 0) return;
    setItems((list) => list.map((i) => ({ ...i, read: true }))); // optimistic
    setUnread(0);
    try {
      await api.markAllNotificationsRead();
    } catch {
      setReloadKey((k) => k + 1);
    }
  }

  if (status === "loading") {
    return (
      <div className="flex justify-center py-24">
        <Spinner label="Loading your notifications" />
      </div>
    );
  }
  if (status === "error") {
    return <ErrorState message="Could not load your notifications." onRetry={retry} />;
  }
  if (items.length === 0) {
    return (
      <EmptyState
        title="No notifications yet"
        message="When someone follows your channel or comments on your video, you'll see it here."
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void markAll()}
          disabled={unread === 0}
          className="text-sm font-medium text-zinc-600 hover:text-zinc-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 disabled:opacity-50 dark:text-zinc-300 dark:hover:text-zinc-100"
        >
          Mark all as read
        </button>
      </div>
      <ul className="flex flex-col divide-y divide-zinc-200 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {items.map((n) => {
          const { text, href } = describe(n);
          return (
            <li
              key={n.id}
              className={
                "flex items-center gap-3 px-4 py-3 " +
                (n.read ? "" : "bg-zinc-50 dark:bg-zinc-900/40")
              }
            >
              <span
                aria-hidden
                className={
                  "h-2 w-2 shrink-0 rounded-full " + (n.read ? "bg-transparent" : "bg-blue-600")
                }
              />
              <div className="flex min-w-0 flex-1 flex-col">
                <Link
                  href={href}
                  onClick={() => void markRead(n.id)}
                  className="truncate text-sm text-zinc-800 hover:underline dark:text-zinc-100"
                >
                  {text}
                </Link>
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  {relativeTime(n.created_at)}
                </span>
              </div>
              {n.read ? null : (
                <button
                  type="button"
                  onClick={() => void markRead(n.id)}
                  aria-label="Mark as read"
                  className="shrink-0 text-xs font-medium text-zinc-500 hover:text-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:hover:text-zinc-200"
                >
                  Mark read
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
