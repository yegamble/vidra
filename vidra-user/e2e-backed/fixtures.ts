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

// The deterministic test admin. The backend grants the admin role to the FIRST
// account on a fresh instance, so `ensureAdmin` must run before any other
// registration — the `backed-setup` Playwright project (a dependency of
// `backend-backed`) guarantees that. These are throwaway credentials for an
// ephemeral CI/dev database, never a real secret.
export const ADMIN_USERNAME = "e2eadmin";
export const ADMIN_EMAIL = "e2e-admin@example.test";
export const ADMIN_PASSWORD = "e2e-admin-supersecret";

/**
 * ensureAdmin registers the deterministic admin (idempotent: a 409 means it already
 * exists from a prior run, which is fine). Run once, first, by the setup project.
 * NOTE: locally this only yields an admin against a FRESH database — reset with
 * `docker compose --profile core down -v` if the dev DB already has other accounts.
 */
export async function ensureAdmin(request: APIRequestContext): Promise<void> {
  await request.post(`${API_URL}/api/v1/auth/register`, {
    data: { username: ADMIN_USERNAME, email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
}

/** adminToken logs in as the deterministic admin and returns its access token. */
export async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  return ((await res.json()) as { token: string }).token;
}

/** reportsQueue reads the admin moderation queue (newest first) as the given admin. */
export async function reportsQueue(
  request: APIRequestContext,
  token: string,
): Promise<Array<{ reason: string; target_type: string; status: string }>> {
  const res = await request.get(`${API_URL}/api/v1/admin/reports?limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return (
    (await res.json()) as { reports: Array<{ reason: string; target_type: string; status: string }> }
  ).reports;
}

/**
 * seedPublishedChannel registers a fresh owner, creates a channel, and publishes
 * one public video in it via the API, returning the channel handle + display name
 * and the owner's access token (for seeding owner-authored data such as comments).
 */
export async function seedPublishedChannel(
  request: APIRequestContext,
): Promise<{ handle: string; displayName: string; videoId: string; videoTitle: string; token: string }> {
  const id = uniqueId();
  const handle = `ch${id}`;
  const displayName = `Channel ${id}`;
  const videoTitle = `Video ${id}`;

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
    data: { title: videoTitle, privacy: "public" },
  });
  const videoId = ((await vid.json()) as { id: string }).id;
  await request.post(`${API_URL}/api/v1/videos/${videoId}/file`, {
    headers: auth,
    multipart: {
      file: { name: "clip.mp4", mimeType: "video/mp4", buffer: Buffer.from(TINY_MP4_BASE64, "base64") },
    },
  });

  return { handle, displayName, videoId, videoTitle, token };
}

/**
 * registerUser registers a fresh account via the API, returning its access token,
 * id, and username. Used to seed a target account for admin user-management tests.
 */
export async function registerUser(
  request: APIRequestContext,
  prefix = "usr",
): Promise<{ token: string; id: string; username: string; email: string }> {
  const id = uniqueId();
  const username = `${prefix}${id}`;
  const email = `e2e-${prefix}-${id}@example.test`;
  const reg = await request.post(`${API_URL}/api/v1/auth/register`, {
    data: { username, email, password: "supersecret-e2e" },
  });
  const body = (await reg.json()) as { token: string; user: { id: string } };
  return { token: body.token, id: body.user.id, username, email };
}

/** adminUsers reads the admin users list (optionally filtered by q) as the admin. */
export async function adminUsers(
  request: APIRequestContext,
  token: string,
  q?: string,
): Promise<Array<{ id: string; username: string; role: string; is_active: boolean }>> {
  const url = new URL(`${API_URL}/api/v1/admin/users`);
  url.searchParams.set("limit", "100");
  if (q) url.searchParams.set("q", q);
  const res = await request.get(url.toString(), {
    headers: { Authorization: `Bearer ${token}` },
  });
  return (
    (await res.json()) as {
      users: Array<{ id: string; username: string; role: string; is_active: boolean }>;
    }
  ).users;
}

/**
 * fileVideoReport registers a fresh reporter and files a report on a video via the
 * API, returning the unique reason used (so a test can find it in the queue). Used
 * to seed an open report for the moderation-resolve UI to act on.
 */
export async function fileVideoReport(
  request: APIRequestContext,
  videoId: string,
): Promise<string> {
  const id = uniqueId();
  const reg = await request.post(`${API_URL}/api/v1/auth/register`, {
    data: { username: `rep${id}`, email: `e2e-rep-${id}@example.test`, password: "supersecret-e2e" },
  });
  const token = ((await reg.json()) as { token: string }).token;
  const reason = `mod-report-${id}`;
  await request.post(`${API_URL}/api/v1/videos/${videoId}/report`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { reason },
  });
  return reason;
}

/** blockVideo blocks a video as the given admin/moderator (POST /admin/videos/:id/block). */
export async function blockVideo(
  request: APIRequestContext,
  token: string,
  videoId: string,
  reason: string,
): Promise<void> {
  await request.post(`${API_URL}/api/v1/admin/videos/${videoId}/block`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { reason },
  });
}

/** blockedVideos reads the moderation block-list (newest block first) as the given admin. */
export async function blockedVideos(
  request: APIRequestContext,
  token: string,
): Promise<Array<{ video_id: string; title: string; reason: string }>> {
  const res = await request.get(`${API_URL}/api/v1/admin/videos/blocked?limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return (
    (await res.json()) as { videos: Array<{ video_id: string; title: string; reason: string }> }
  ).videos;
}

/** videoIsPublic reports whether GET /videos/:id is publicly reachable (200 = visible). */
export async function videoIsPublic(request: APIRequestContext, videoId: string): Promise<boolean> {
  const res = await request.get(`${API_URL}/api/v1/videos/${videoId}`);
  return res.status() === 200;
}

/** captions reads a video's caption tracks via the public API. */
export async function captions(
  request: APIRequestContext,
  videoId: string,
): Promise<Array<{ language: string; label: string }>> {
  const res = await request.get(`${API_URL}/api/v1/videos/${videoId}/captions`);
  return ((await res.json()) as { captions: Array<{ language: string; label: string }> }).captions;
}

/** seedCaption uploads a WebVTT caption track to a video as its owner (multipart). */
export async function seedCaption(
  request: APIRequestContext,
  videoId: string,
  token: string,
  language: string,
  label: string,
): Promise<void> {
  await request.post(`${API_URL}/api/v1/videos/${videoId}/captions`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: {
      language,
      label,
      file: {
        name: "cap.vtt",
        mimeType: "text/vtt",
        buffer: Buffer.from("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n"),
      },
    },
  });
}

/**
 * devEmailToken reads the most recent captured account-security token for an
 * email via the DEV-ONLY endpoint (requires DEV_MAIL_CAPTURE_ENABLED=true on the
 * backend). Lets the backed suite complete the reset / email-verify confirm flows
 * with the token the backend would otherwise only deliver out-of-band.
 */
export async function devEmailToken(
  request: APIRequestContext,
  email: string,
  kind: "reset" | "verification" = "reset",
): Promise<string> {
  const res = await request.get(
    `${API_URL}/api/v1/dev/email-token?email=${encodeURIComponent(email)}&kind=${kind}`,
  );
  return ((await res.json()) as { token: string }).token;
}

/** watchedWords reads the instance watched-words list as the given admin. */
export async function watchedWords(
  request: APIRequestContext,
  token: string,
): Promise<Array<{ id: string; word: string }>> {
  const res = await request.get(`${API_URL}/api/v1/admin/watched-words?limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return ((await res.json()) as { words: Array<{ id: string; word: string }> }).words;
}

/** seedComment posts a comment on a video as the given user, returning its id. */
export async function seedComment(
  request: APIRequestContext,
  videoId: string,
  token: string,
  body: string,
): Promise<string> {
  const res = await request.post(`${API_URL}/api/v1/videos/${videoId}/comments`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { body },
  });
  return ((await res.json()) as { id: string }).id;
}

/** followerCount reads a channel's persisted follower count via the public API. */
export async function followerCount(request: APIRequestContext, handle: string): Promise<number> {
  const res = await request.get(`${API_URL}/api/v1/channels/${handle}`);
  return ((await res.json()) as { follower_count: number }).follower_count;
}

/** videoComments reads a video's persisted comments via the public API. */
export async function videoComments(
  request: APIRequestContext,
  videoId: string,
): Promise<Array<{ body: string; author_username: string }>> {
  const res = await request.get(`${API_URL}/api/v1/videos/${videoId}/comments`);
  return ((await res.json()) as { comments: Array<{ body: string; author_username: string }> }).comments;
}

/** videoDetail reads a video's public detail (title/description/taxonomy) via the API. */
export async function videoDetail(
  request: APIRequestContext,
  videoId: string,
): Promise<{
  title: string;
  description: string;
  category?: string;
  language?: string;
  license?: string;
}> {
  const res = await request.get(`${API_URL}/api/v1/videos/${videoId}`);
  return (await res.json()) as {
    title: string;
    description: string;
    category?: string;
    language?: string;
    license?: string;
  };
}

/** channelVideos reads a channel's public videos via the public API. */
export async function channelVideos(
  request: APIRequestContext,
  handle: string,
): Promise<Array<{ id: string; title: string; privacy: string; state: string }>> {
  const res = await request.get(`${API_URL}/api/v1/channels/${handle}/videos`);
  return (
    (await res.json()) as {
      videos: Array<{ id: string; title: string; privacy: string; state: string }>;
    }
  ).videos;
}

/** videoRating reads a video's persisted like/dislike counts via the public API. */
export async function videoRating(
  request: APIRequestContext,
  videoId: string,
): Promise<{ like_count: number; dislike_count: number }> {
  const res = await request.get(`${API_URL}/api/v1/videos/${videoId}/rating`);
  return (await res.json()) as { like_count: number; dislike_count: number };
}
