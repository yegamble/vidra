import { apiBaseUrl } from "@/lib/config";

import { apiRequest } from "./client";
import type {
  Channel,
  FeedSort,
  InstanceResponse,
  Video,
  VideoFeedResponse,
  VideoListResponse,
  VideoSearchResponse,
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
};

/** Direct URL to a video's original stream (for a <video> src). Range-capable. */
export function videoOriginalUrl(id: string): string {
  return `${apiBaseUrl}/api/v1/videos/${encodeURIComponent(id)}/original`;
}

/** Direct URL to a video's poster image (for an <img> src). */
export function videoThumbnailUrl(id: string): string {
  return `${apiBaseUrl}/api/v1/videos/${encodeURIComponent(id)}/thumbnail`;
}
