import Link from "next/link";

import { videoThumbnailUrl } from "@/lib/api";
import type { Video } from "@/lib/api";
import { formatCount, relativeTime } from "@/lib/format";

export function VideoCard({ video }: { video: Video }) {
  const meta: string[] = [];
  if (typeof video.views === "number") meta.push(`${formatCount(video.views)} views`);
  const when = relativeTime(video.created_at);
  if (when) meta.push(when);

  // The card is a <div>, not a single <Link>, so the channel can be its own
  // (sibling, non-nested) link to /channels/{handle}.
  return (
    <div className="flex flex-col gap-2">
      <Link
        href={`/videos/${video.id}`}
        className="group flex flex-col gap-2 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500"
      >
        <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-zinc-200 dark:bg-zinc-800">
          {video.has_thumbnail ? (
            // Backend-served image; a plain <img> avoids next/image remote config.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={videoThumbnailUrl(video.id)}
              alt={video.title}
              loading="lazy"
              className="h-full w-full object-cover transition-transform group-hover:scale-[1.02]"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-xs text-zinc-400">
              No preview
            </div>
          )}
        </div>
        <h3 className="line-clamp-2 text-sm font-medium text-zinc-900 group-hover:text-zinc-600 dark:text-zinc-100 dark:group-hover:text-zinc-300">
          {video.title}
        </h3>
      </Link>
      {video.channel_handle ? (
        <Link
          href={`/channels/${video.channel_handle}`}
          className="text-xs text-zinc-500 hover:text-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-zinc-500 dark:text-zinc-400 dark:hover:text-zinc-200"
        >
          {video.channel_display_name || video.channel_handle}
        </Link>
      ) : null}
      {meta.length > 0 ? (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{meta.join(" · ")}</p>
      ) : null}
    </div>
  );
}
