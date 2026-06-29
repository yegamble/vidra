import { apiBaseUrl } from "@/lib/config";

import { apiRequest } from "./client";
import type {
  Channel,
  Comment,
  CommentListResponse,
  FeedSort,
  InstanceResponse,
  RatingValue,
  Video,
  VideoFeedResponse,
  VideoListResponse,
  VideoRating,
  VideoSearchResponse,
  WatchHistoryResponse,
  WatchProgress,
} from "./types";

export interface FeedParams {
  sort?: FeedSort;
  limit?: number;
  offset?: number;
}

export interface SearchParams {
  limit?: number;
  offset?: number;
}

/** Typed wrappers for the public vidra-core read endpoints. */
export const api = {
  /** GET /api/v1/instance — public instance about/config. */
  getInstance: (signal?: AbortSignal) =>
    apiRequest<InstanceResponse>("/api/v1/instance", { signal }),

  /** GET /api/v1/videos — public feed, ordered by sort, with view/thumbnail cards. */
  getFeed: (params: FeedParams = {}, signal?: AbortSignal) =>
    apiRequest<VideoFeedResponse>("/api/v1/videos", {
      query: { sort: params.sort, limit: params.limit, offset: params.offset },
      signal,
    }),

  /** GET /api/v1/videos/{id} — video detail (private → owner only, else 404). */
  getVideo: (id: string, token?: string, signal?: AbortSignal) =>
    apiRequest<Video>(`/api/v1/videos/${encodeURIComponent(id)}`, { token, signal }),

  /** GET /api/v1/videos/search?q= — public title search. */
  searchVideos: (query: string, params: SearchParams = {}, signal?: AbortSignal) =>
    apiRequest<VideoSearchResponse>("/api/v1/videos/search", {
      query: { q: query, limit: params.limit, offset: params.offset },
      signal,
    }),

  /** GET /api/v1/channels/{handle} — channel by handle. */
  getChannel: (handle: string, signal?: AbortSignal) =>
    apiRequest<Channel>(`/api/v1/channels/${encodeURIComponent(handle)}`, { signal }),

  /** GET /api/v1/channels/{handle}/videos — a channel's videos (cards). */
  listChannelVideos: (handle: string, token?: string, signal?: AbortSignal) =>
    apiRequest<VideoListResponse>(
      `/api/v1/channels/${encodeURIComponent(handle)}/videos`,
      { token, signal },
    ),

  /** POST /api/v1/channels/{handle}/follow — follow a channel (auth; idempotent 204). */
  followChannel: (handle: string) =>
    apiRequest<void>(`/api/v1/channels/${encodeURIComponent(handle)}/follow`, { method: "POST" }),

  /** DELETE /api/v1/channels/{handle}/follow — unfollow a channel (auth; idempotent 204). */
  unfollowChannel: (handle: string) =>
    apiRequest<void>(`/api/v1/channels/${encodeURIComponent(handle)}/follow`, { method: "DELETE" }),

  /** GET /api/v1/me/subscriptions/videos — videos from followed channels (auth). */
  getSubscriptionVideos: (params: SearchParams = {}, signal?: AbortSignal) =>
    apiRequest<VideoFeedResponse>("/api/v1/me/subscriptions/videos", {
      query: { limit: params.limit, offset: params.offset },
      signal,
    }),

  /** GET /api/v1/videos/{id}/comments — a public video's comments, newest first. */
  getVideoComments: (id: string, params: SearchParams = {}, signal?: AbortSignal) =>
    apiRequest<CommentListResponse>(
      `/api/v1/videos/${encodeURIComponent(id)}/comments`,
      { query: { limit: params.limit, offset: params.offset }, signal },
    ),

  /** POST /api/v1/videos/{id}/comments — post a comment on a video (auth). */
  postComment: (id: string, body: string) =>
    apiRequest<Comment>(`/api/v1/videos/${encodeURIComponent(id)}/comments`, {
      method: "POST",
      body: { body },
    }),

  /** DELETE /api/v1/comments/{id} — delete your own comment (auth). */
  deleteComment: (id: string) =>
    apiRequest<void>(`/api/v1/comments/${encodeURIComponent(id)}`, { method: "DELETE" }),

  /** GET /api/v1/videos/{id}/rating — like/dislike counts (+ my_rating if authed). */
  getVideoRating: (id: string, signal?: AbortSignal) =>
    apiRequest<VideoRating>(`/api/v1/videos/${encodeURIComponent(id)}/rating`, { signal }),

  /** PUT /api/v1/videos/{id}/rating — set/change your rating (auth). */
  setVideoRating: (id: string, rating: RatingValue) =>
    apiRequest<VideoRating>(`/api/v1/videos/${encodeURIComponent(id)}/rating`, {
      method: "PUT",
      body: { rating },
    }),

  /** DELETE /api/v1/videos/{id}/rating — clear your rating (auth). */
  clearVideoRating: (id: string) =>
    apiRequest<VideoRating>(`/api/v1/videos/${encodeURIComponent(id)}/rating`, { method: "DELETE" }),

  /** GET /api/v1/me/saved — the caller's saved videos as cards (auth). */
  getSavedVideos: (params: SearchParams = {}, signal?: AbortSignal) =>
    apiRequest<VideoFeedResponse>("/api/v1/me/saved", {
      query: { limit: params.limit, offset: params.offset },
      signal,
    }),

  /** POST /api/v1/videos/{id}/save — save a video to your library (auth, idempotent). */
  saveVideo: (id: string) =>
    apiRequest<void>(`/api/v1/videos/${encodeURIComponent(id)}/save`, { method: "POST" }),

  /** DELETE /api/v1/videos/{id}/save — remove a video from your library (auth, idempotent). */
  unsaveVideo: (id: string) =>
    apiRequest<void>(`/api/v1/videos/${encodeURIComponent(id)}/save`, { method: "DELETE" }),

  /** GET /api/v1/me/history — the caller's watch history as cards, newest-watched first (auth). */
  getWatchHistory: (params: SearchParams = {}, signal?: AbortSignal) =>
    apiRequest<WatchHistoryResponse>("/api/v1/me/history", {
      query: { limit: params.limit, offset: params.offset },
      signal,
    }),

  /** GET /api/v1/videos/{id}/watch-progress — the caller's saved resume position (auth). */
  getWatchProgress: (id: string, signal?: AbortSignal) =>
    apiRequest<WatchProgress>(`/api/v1/videos/${encodeURIComponent(id)}/watch-progress`, { signal }),

  /** PUT /api/v1/videos/{id}/watch-progress — record the caller's resume position (auth, 204). */
  recordWatchProgress: (id: string, positionSeconds: number) =>
    apiRequest<void>(`/api/v1/videos/${encodeURIComponent(id)}/watch-progress`, {
      method: "PUT",
      body: { position_seconds: positionSeconds },
    }),

  /** DELETE /api/v1/me/history/{id} — remove one video from history (auth, idempotent). */
  deleteHistoryEntry: (id: string) =>
    apiRequest<void>(`/api/v1/me/history/${encodeURIComponent(id)}`, { method: "DELETE" }),

  /** DELETE /api/v1/me/history — clear the caller's entire watch history (auth, idempotent). */
  clearWatchHistory: () => apiRequest<void>("/api/v1/me/history", { method: "DELETE" }),
};

/** Direct URL to a video's original stream (for a <video> src). Range-capable. */
export function videoOriginalUrl(id: string): string {
  return `${apiBaseUrl}/api/v1/videos/${encodeURIComponent(id)}/original`;
}

/** Direct URL to a video's poster image (for an <img> src). */
export function videoThumbnailUrl(id: string): string {
  return `${apiBaseUrl}/api/v1/videos/${encodeURIComponent(id)}/thumbnail`;
}
