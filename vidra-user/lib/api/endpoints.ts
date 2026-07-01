import { apiBaseUrl } from "@/lib/config";

import { apiRequest } from "./client";
import type {
  AdminUser,
  AdminUserListResponse,
  BlockedVideoListResponse,
  BlockVideoRequest,
  Channel,
  ChannelListResponse,
  Comment,
  CommentListResponse,
  MutedAccountListResponse,
  CreateChannelRequest,
  CreateVideoRequest,
  FeedSort,
  InstanceResponse,
  RatingValue,
  Video,
  VideoFeedResponse,
  VideoListResponse,
  CreatePlaylistRequest,
  NotificationListResponse,
  Playlist,
  PlaylistDetail,
  PlaylistListResponse,
  ReportListResponse,
  ResolveReportRequest,
  UnreadCountResponse,
  UpdateUserRequest,
  UpdatePlaylistRequest,
  UpdateVideoRequest,
  UploadVideoResult,
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

  /** GET /api/v1/me/channels — the caller's own channels (auth). */
  getMyChannels: (signal?: AbortSignal) =>
    apiRequest<ChannelListResponse>("/api/v1/me/channels", { signal }),

  /** POST /api/v1/channels — create a channel (auth). */
  createChannel: (body: CreateChannelRequest) =>
    apiRequest<Channel>("/api/v1/channels", { method: "POST", body }),

  /** POST /api/v1/channels/{handle}/videos — create a draft video (auth, owner). */
  createVideoDraft: (handle: string, body: CreateVideoRequest) =>
    apiRequest<Video>(`/api/v1/channels/${encodeURIComponent(handle)}/videos`, {
      method: "POST",
      body,
    }),

  /** PATCH /api/v1/videos/{id} — update a video's metadata (auth, owner). */
  updateVideo: (id: string, body: UpdateVideoRequest) =>
    apiRequest<Video>(`/api/v1/videos/${encodeURIComponent(id)}`, { method: "PATCH", body }),

  /** DELETE /api/v1/videos/{id} — delete a video (auth, owner; idempotent 204). */
  deleteVideo: (id: string) =>
    apiRequest<void>(`/api/v1/videos/${encodeURIComponent(id)}`, { method: "DELETE" }),

  /**
   * POST /api/v1/videos/{id}/file — upload the original file (auth, owner). The
   * multipart body moves the draft to processing and (with no prober) publishes it.
   */
  uploadVideoFile: (videoId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiRequest<UploadVideoResult>(`/api/v1/videos/${encodeURIComponent(videoId)}/file`, {
      method: "POST",
      body: form,
    });
  },

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

  /** POST /api/v1/me/mutes/accounts/{id} — mute an account (auth; idempotent 204). */
  muteAccount: (userId: string) =>
    apiRequest<void>(`/api/v1/me/mutes/accounts/${encodeURIComponent(userId)}`, {
      method: "POST",
    }),

  /** DELETE /api/v1/me/mutes/accounts/{id} — unmute an account (auth; idempotent 204). */
  unmuteAccount: (userId: string) =>
    apiRequest<void>(`/api/v1/me/mutes/accounts/${encodeURIComponent(userId)}`, {
      method: "DELETE",
    }),

  /** GET /api/v1/me/mutes/accounts — the accounts the caller has muted, newest first (auth). */
  getMutedAccounts: (params: { limit?: number; offset?: number } = {}, signal?: AbortSignal) =>
    apiRequest<MutedAccountListResponse>("/api/v1/me/mutes/accounts", {
      query: { limit: params.limit, offset: params.offset },
      signal,
    }),

  /** POST /api/v1/videos/{id}/report — file an abuse report on a video (auth; idempotent 204). */
  reportVideo: (id: string, reason: string) =>
    apiRequest<void>(`/api/v1/videos/${encodeURIComponent(id)}/report`, {
      method: "POST",
      body: { reason },
    }),

  /** POST /api/v1/comments/{id}/report — file an abuse report on a comment (auth; idempotent 204). */
  reportComment: (id: string, reason: string) =>
    apiRequest<void>(`/api/v1/comments/${encodeURIComponent(id)}/report`, {
      method: "POST",
      body: { reason },
    }),

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

  /** GET /api/v1/me/notifications — the caller's notifications + unread count (auth). */
  getNotifications: (
    params: { unread?: boolean; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) =>
    apiRequest<NotificationListResponse>("/api/v1/me/notifications", {
      query: { unread: params.unread, limit: params.limit, offset: params.offset },
      signal,
    }),

  /** GET /api/v1/me/notifications/unread-count — just the unread count, for a badge (auth). */
  getUnreadNotificationCount: (signal?: AbortSignal) =>
    apiRequest<UnreadCountResponse>("/api/v1/me/notifications/unread-count", { signal }),

  /** POST /api/v1/me/notifications/{id}/read — mark one notification read (auth, idempotent). */
  markNotificationRead: (id: string) =>
    apiRequest<void>(`/api/v1/me/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }),

  /** POST /api/v1/me/notifications/read-all — mark all notifications read (auth, idempotent). */
  markAllNotificationsRead: () =>
    apiRequest<void>("/api/v1/me/notifications/read-all", { method: "POST" }),

  /** GET /api/v1/me/playlists — the caller's playlists, newest first (auth). */
  getMyPlaylists: (signal?: AbortSignal) =>
    apiRequest<PlaylistListResponse>("/api/v1/me/playlists", { signal }),

  /** POST /api/v1/playlists — create a playlist (auth). */
  createPlaylist: (body: CreatePlaylistRequest) =>
    apiRequest<Playlist>("/api/v1/playlists", { method: "POST", body }),

  /** GET /api/v1/playlists/{id} — a playlist + its ordered video cards. */
  getPlaylist: (id: string, signal?: AbortSignal) =>
    apiRequest<PlaylistDetail>(`/api/v1/playlists/${encodeURIComponent(id)}`, { signal }),

  /** PATCH /api/v1/playlists/{id} — update a playlist (auth, owner). */
  updatePlaylist: (id: string, body: UpdatePlaylistRequest) =>
    apiRequest<Playlist>(`/api/v1/playlists/${encodeURIComponent(id)}`, { method: "PATCH", body }),

  /** DELETE /api/v1/playlists/{id} — delete a playlist (auth, owner). */
  deletePlaylist: (id: string) =>
    apiRequest<void>(`/api/v1/playlists/${encodeURIComponent(id)}`, { method: "DELETE" }),

  /** POST /api/v1/playlists/{id}/videos — add a video to a playlist (auth, owner, idempotent). */
  addToPlaylist: (id: string, videoId: string) =>
    apiRequest<void>(`/api/v1/playlists/${encodeURIComponent(id)}/videos`, {
      method: "POST",
      body: { video_id: videoId },
    }),

  /** DELETE /api/v1/playlists/{id}/videos/{videoId} — remove a video (auth, owner, idempotent). */
  removeFromPlaylist: (id: string, videoId: string) =>
    apiRequest<void>(
      `/api/v1/playlists/${encodeURIComponent(id)}/videos/${encodeURIComponent(videoId)}`,
      { method: "DELETE" },
    ),

  /**
   * GET /api/v1/admin/reports — the moderation queue, newest first (moderator/admin).
   * Pass `openOnly` to return only unresolved reports.
   */
  getReports: (
    params: { openOnly?: boolean; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) =>
    apiRequest<ReportListResponse>("/api/v1/admin/reports", {
      query: {
        status: params.openOnly ? "open" : undefined,
        limit: params.limit,
        offset: params.offset,
      },
      signal,
    }),

  /** POST /api/v1/admin/reports/{id}/resolve — accept/reject a report (moderator/admin, 204). */
  resolveReport: (id: string, body: ResolveReportRequest) =>
    apiRequest<void>(`/api/v1/admin/reports/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      body,
    }),

  /**
   * GET /api/v1/admin/users — accounts newest first (admin only). Optional `q`
   * filters by a username/email substring. Paginated via limit/offset.
   */
  getAdminUsers: (
    params: { q?: string; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) =>
    apiRequest<AdminUserListResponse>("/api/v1/admin/users", {
      query: { q: params.q, limit: params.limit, offset: params.offset },
      signal,
    }),

  /** PATCH /api/v1/admin/users/{id} — edit a user's role / active flag (admin only). */
  updateAdminUser: (id: string, body: UpdateUserRequest) =>
    apiRequest<AdminUser>(`/api/v1/admin/users/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body,
    }),

  /**
   * GET /api/v1/admin/videos/blocked — currently-blocked videos, newest block
   * first (moderator/admin). Paginated via limit/offset.
   */
  getBlockedVideos: (
    params: { limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) =>
    apiRequest<BlockedVideoListResponse>("/api/v1/admin/videos/blocked", {
      query: { limit: params.limit, offset: params.offset },
      signal,
    }),

  /**
   * POST /api/v1/admin/videos/{id}/block — block a video so it is hidden from
   * public surfaces (moderator/admin, idempotent, 204). The optional reason is
   * recorded for the audit trail.
   */
  blockVideo: (id: string, body: BlockVideoRequest = {}) =>
    apiRequest<void>(`/api/v1/admin/videos/${encodeURIComponent(id)}/block`, {
      method: "POST",
      body,
    }),

  /** DELETE /api/v1/admin/videos/{id}/block — lift a video's block (moderator/admin, idempotent, 204). */
  unblockVideo: (id: string) =>
    apiRequest<void>(`/api/v1/admin/videos/${encodeURIComponent(id)}/block`, {
      method: "DELETE",
    }),
};

/** Direct URL to a video's original stream (for a <video> src). Range-capable. */
export function videoOriginalUrl(id: string): string {
  return `${apiBaseUrl}/api/v1/videos/${encodeURIComponent(id)}/original`;
}

/** Direct URL to a video's poster image (for an <img> src). */
export function videoThumbnailUrl(id: string): string {
  return `${apiBaseUrl}/api/v1/videos/${encodeURIComponent(id)}/thumbnail`;
}
