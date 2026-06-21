import { randomUUID } from "node:crypto";

import type { APIRequestContext } from "@playwright/test";

// A tiny (16x16, ~0.1s) valid H.264 mp4 generated with ffmpeg, base64-encoded.
// The e2e backend runs a real ffprobe that rejects non-video bytes, so seeding a
// *publishable* video needs real video data. This is a synthetic black-frame clip
// (not a committed binary, not PII) so the backed tests can publish a video via
// the API without depending on ffmpeg being installed on the runner.
export const TINY_MP4_BASE64 =
  "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAAAuVtZGF0AAACrgYF//+q3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NSByMzIyMiBiMzU2MDVhIC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0xIHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTEgbG9va2FoZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWluPTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAAD2WIhAAz//727L4FNhTIwQAAAAhBmiJsQr/+wAAAAAgBnkF5Cv/EgQAAA11tb292AAAAbG12aGQAAAAAAAAAAAAAAAAAAAPoAAAAeAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAACh3RyYWsAAABcdGtoZAAAAAMAAAAAAAAAAAAAAAEAAAAAAAAAeAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAEAAAABAAAAAAACRlZHRzAAAAHGVsc3QAAAAAAAAAAQAAAHgAAAQAAAEAAAAAAf9tZGlhAAAAIG1kaGQAAAAAAAAAAAAAAAAAADIAAAAIAFXEAAAAAAAtaGRscgAAAAAAAAAAdmlkZQAAAAAAAAAAAAAAAFZpZGVvSGFuZGxlcgAAAAGqbWluZgAAABR2bWhkAAAAAQAAAAAAAAAAAAAAJGRpbmYAAAAcZHJlZgAAAAAAAAABAAAADHVybCAAAAABAAABanN0YmwAAAC+c3RzZAAAAAAAAAABAAAArmF2YzEAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAEAAQAEgAAABIAAAAAAAAAAEVTGF2YzYyLjI4LjEwMCBsaWJ4MjY0AAAAAAAAAAAAAAAY//8AAAA0YXZjQwFkAAr/4QAXZ2QACqzZXsBEAAADAAQAAAMAyDxIllgBAAZo6+PLIsD9+PgAAAAAEHBhc3AAAAABAAAAAQAAABRidHJ0AAAAAAAAvuIAAAAAAAAAGHN0dHMAAAAAAAAAAQAAAAMAAAIAAAAAFHN0c3MAAAAAAAAAAQAAAAEAAAAoY3R0cwAAAAAAAAADAAAAAQAABAAAAAABAAAGAAAAAAEAAAIAAAAAHHN0c2MAAAAAAAAAAQAAAAEAAAADAAAAAQAAACBzdHN6AAAAAAAAAAAAAAADAAACxQAAAAwAAAAMAAAAFHN0Y28AAAAAAAAAAQAAADAAAABidWR0YQAAAFptZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAAAC1pbHN0AAAAJal0b28AAAAdZGF0YQAAAAEAAAAATGF2ZjYyLjEyLjEwMA==";

// The backend base URL for direct API seeding (the UI runs at :3000). Defaults to
// the CI backend (:8080); set E2E_API_URL=http://localhost:8088 for local runs.
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8080";

export function uniqueId(): string {
  return randomUUID().replace(/-/g, "").slice(0, 12);
}

/**
 * seedPublishedChannel registers a fresh owner, creates a channel, and publishes
 * one public video in it via the API, returning the channel handle + display name.
 */
export async function seedPublishedChannel(
  request: APIRequestContext,
): Promise<{ handle: string; displayName: string }> {
  const id = uniqueId();
  const handle = `ch${id}`;
  const displayName = `Channel ${id}`;

  const reg = await request.post(`${API_URL}/api/v1/auth/register`, {
    data: { username: `owner${id}`, email: `e2e-owner-${id}@example.test`, password: "supersecret-e2e" },
  });
  const token = ((await reg.json()) as { token: string }).token;
  const auth = { Authorization: `Bearer ${token}` };

  await request.post(`${API_URL}/api/v1/channels`, {
    headers: auth,
    data: { handle, display_name: displayName },
  });
  const vid = await request.post(`${API_URL}/api/v1/channels/${handle}/videos`, {
    headers: auth,
    data: { title: `Video ${id}`, privacy: "public" },
  });
  const videoId = ((await vid.json()) as { id: string }).id;
  await request.post(`${API_URL}/api/v1/videos/${videoId}/file`, {
    headers: auth,
    multipart: {
      file: { name: "clip.mp4", mimeType: "video/mp4", buffer: Buffer.from(TINY_MP4_BASE64, "base64") },
    },
  });

  return { handle, displayName };
}

/** followerCount reads a channel's persisted follower count via the public API. */
export async function followerCount(request: APIRequestContext, handle: string): Promise<number> {
  const res = await request.get(`${API_URL}/api/v1/channels/${handle}`);
  return ((await res.json()) as { follower_count: number }).follower_count;
}
