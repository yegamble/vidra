# Vidra Core ↔ PeerTube API Deviations

This document catalogs all known differences between vidra-core's REST API and PeerTube's API v1 specification. These deviations are identified by the integration test suite and maintained as the codebase evolves.

## 1. Response Envelope

vidra-core wraps all JSON responses in a standard envelope:

```json
{
  "success": true,
  "data": { ... },
  "meta": { "total": 100, "limit": 25, "offset": 0 }
}
```

PeerTube returns flat responses:

```json
{
  "total": 100,
  "data": [ ... ]
}
```

**Frontend handling:** `unwrapEnvelope()` in `src/lib/api/client.ts` strips the vidra-core envelope and flattens paginated responses to `{ data, total }`.

## 2. Entity Casing Differences

| Entity | vidra-core | PeerTube | Notes |
|--------|-----------|----------|-------|
| Video | snake_case (`upload_date`, `created_at`, `user_id`) | camelCase (`publishedAt`, `createdAt`, `account`) | Different field names entirely |
| Channel | camelCase (`displayName`, `avatarUrl`, `createdAt`) | camelCase (`displayName`, `avatarPath`, `createdAt`) | Close but avatar field differs |
| Comment | snake_case (`user_id`, `body`, `created_at`) | camelCase (`account`, `text`, `createdAt`) | Field names and nesting differ |
| Playlist | snake_case (`item_count`, `user_id`, `name`) | camelCase (`videosLength`, `ownerAccount`, `displayName`) | Field names differ |
| Notification | snake_case (`user_id`, `created_at`) + string enum types | Numeric enum types + nested objects | Type system differs |
| User | snake_case (`created_at`, `is_active`) | camelCase (`createdAt`) + nested `account` | Structure differs |

## 3. Auth Flow Differences

| Aspect | vidra-core | PeerTube |
|--------|-----------|----------|
| Registration | `POST /api/v1/auth/register` | `POST /api/v1/users/register` |
| Login | `POST /api/v1/auth/login` (convenience) | Only `POST /api/v1/users/token` (OAuth2) |
| Token endpoint | `/oauth/token` (standard) | `/api/v1/users/token` |
| Auth response | `{ user, access_token, refresh_token, expires_in }` | `{ access_token, token_type, expires_in, refresh_token }` |
| 2FA | `/api/v1/auth/2fa/*` | `/api/v1/users/two-factor/*` |
| Profile | `/api/v1/users/me` | `/api/v1/users/me` (same) |

## 4. Endpoint Path Differences

| Feature | vidra-core Path | PeerTube Path | Status |
|---------|----------------|---------------|--------|
| Video rating | `PUT /api/v1/videos/{id}/rating` | `PUT /api/v1/videos/{id}/rate` | Alias added |
| Video description | Included in `GET /videos/{id}` | `GET /api/v1/videos/{id}/description` | Alias added |
| Watch progress | `POST /api/v1/videos/{id}/views` | `PUT /api/v1/videos/{id}/watching` | Alias added |
| Video overview | `GET /api/v1/trending` | `GET /api/v1/overviews/videos` | Alias added |
| Notification settings | `PUT /api/v1/users/me/notification-preferences` | `PUT /api/v1/users/me/notification-settings` | Alias added |
| Notification list | `/api/v1/notifications/*` | `/api/v1/users/me/notifications/*` | Alias added (already existed) |
| Blocklist | `/api/v1/blocklist/*` | `/api/v1/users/me/blocklist/*` | Alias added (already existed) |
| Bulk comment remove | `POST /api/v1/bulk/comments/remove` | `POST /api/v1/bulk/remove-comments-of` | Alias added |
| Redundancy | N/A (uses IPFS) | `GET /api/v1/server/redundancy/{host}` | Returns 501 |
| Jobs | `GET /api/v1/admin/jobs/{state}` | `GET /api/v1/jobs/{state}` | Already existed at both paths |

## 5. Stubbed PeerTube Endpoints (Return 501)

These PeerTube API endpoints are registered but return `501 Not Implemented`:

| Feature | Endpoint Count | Notes |
|---------|---------------|-------|
| Channel Collaborators | 5 | Invite, accept, reject, delete, list |
| Remote Runners | 17+ | Full runner system (register, jobs, files) |
| User Registration Moderation | 4 | Accept, reject, delete, list registrations |
| Resumable Upload (PeerTube style) | 2 | PUT/DELETE for PeerTube's upload-resumable format |
| Server Redundancy | 1 | Vidra uses IPFS instead |

## 6. Privacy Values

| vidra-core | PeerTube |
|-----------|----------|
| String: `"public"`, `"unlisted"`, `"private"` | Numeric: `1` (public), `2` (unlisted), `3` (private), `4` (internal) |

vidra-core uses string privacy values throughout. PeerTube uses numeric IDs. The frontend handles vidra-core's strings natively.

## 7. Video Thumbnail/Preview URLs

| vidra-core | PeerTube |
|-----------|----------|
| `thumbnail_url` (full URL) | `previewPath` / `thumbnailPath` (relative paths) |

vidra-core returns full URLs; PeerTube returns relative paths that must be prefixed with the instance URL.

## 8. Not Applicable Features

These PeerTube features don't have direct equivalents in vidra-core:

- **P2P/WebTorrent statistics** — Vidra uses IPFS for distribution
- **Video redundancy management** — Handled by IPFS
- **Plugin system hooks** — Vidra has its own plugin API (different hook signatures)
- **Custom CSS/JS injection** — Not supported

---

*Last updated: 2026-04-13*
*Generated by integration test discovery and manual audit.*
