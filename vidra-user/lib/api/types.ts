// Hand-maintained types mirroring the vidra-core HTTP contract
// (vidra-core/api/openapi.yaml). PROVISIONAL: keep in lock-step with the backend
// OpenAPI until generated types replace these. Never invent shapes here.

/** A field-level validation problem (present on 422 responses). */
export interface FieldError {
  field: string;
  message: string;
}

/** The single error envelope returned for every non-2xx response. */
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id?: string;
    fields?: FieldError[];
  };
}

export interface InstanceResponse {
  name: string;
  description: string;
  software: { name: string; version: string };
  registration_enabled: boolean;
  terms_url: string;
  privacy_url: string;
  contact_email: string;
}

export type VideoPrivacy = "public" | "unlisted" | "private";
export type VideoState = "draft" | "processing" | "published" | "failed";

export interface Video {
  id: string;
  channel_id: string;
  title: string;
  description: string;
  privacy: VideoPrivacy;
  state: VideoState;
  created_at: string;
  // Discovery-card / detail extras — present on the endpoints that populate them,
  // omitted otherwise.
  duration_seconds?: number;
  width?: number;
  height?: number;
  has_thumbnail?: boolean;
  views?: number;
  // Owning channel, present on card/feed views (so a card can link to the
  // channel); omitted on the detail view.
  channel_handle?: string;
  channel_display_name?: string;
}

export type FeedSort = "recent" | "popular" | "trending";

export interface VideoFeedResponse {
  videos: Video[];
  sort: FeedSort;
  limit: number;
  offset: number;
}

export interface VideoListResponse {
  videos: Video[];
}

export interface VideoSearchResponse {
  query: string;
  videos: Video[];
  limit: number;
  offset: number;
}

export type UserRole = "user" | "moderator" | "admin";

export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  email_verified: boolean;
  display_name: string;
  bio: string;
  created_at: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

/** PATCH /api/v1/auth/me — partial profile update; omitted fields are unchanged. */
export interface UpdateProfileRequest {
  display_name?: string;
  bio?: string;
}

/** Returned by register / login / refresh. */
export interface AuthResponse {
  token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Channel {
  id: string;
  owner_id: string;
  handle: string;
  display_name: string;
  description: string;
  follower_count: number;
  created_at: string;
}

export interface Comment {
  id: string;
  video_id: string;
  body: string;
  author_username: string;
  author_display_name: string;
  created_at: string;
  updated_at: string;
}

export interface CommentListResponse {
  comments: Comment[];
  limit: number;
  offset: number;
}

export type RatingValue = "like" | "dislike";

export interface VideoRating {
  like_count: number;
  dislike_count: number;
  my_rating: RatingValue | null;
}
