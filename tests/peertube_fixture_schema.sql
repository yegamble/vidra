-- IMPORTER QUERY SCHEMA SUBSET ONLY. Not an upstream PeerTube schema/export.
-- Grounded in vidra-core 04a7f0e127177b631eb323d04d330673fee044f9
-- internal/peertubeimport/source.go and seedPeerTube integration fixtures.
-- Deliberately omits upstream constraints, indexes, sequences and application behavior.
CREATE TABLE application (id integer PRIMARY KEY, "migrationVersion" integer NOT NULL);
CREATE TABLE actor (
 id integer PRIMARY KEY, type text NOT NULL, "preferredUsername" text NOT NULL,
 url text, "publicKey" text, "privateKey" text, "serverId" integer,
 "accountId" integer, "videoChannelId" integer,
 "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE account (id integer PRIMARY KEY, name text, "userId" integer);
CREATE TABLE "user" (
 id integer PRIMARY KEY, username text NOT NULL, email text NOT NULL, password text,
 role integer NOT NULL, "emailVerified" boolean, blocked boolean NOT NULL DEFAULT false,
 "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE "videoChannel" (
 id integer PRIMARY KEY, name text NOT NULL, description text, support text,
 "accountId" integer NOT NULL,
 "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE video (
 id integer PRIMARY KEY, uuid uuid NOT NULL, "channelId" integer NOT NULL,
 name text NOT NULL, description text, privacy integer NOT NULL, state integer NOT NULL,
 category integer, licence integer, language text, support text, duration integer NOT NULL,
 views integer NOT NULL DEFAULT 0, nsfw boolean NOT NULL DEFAULT false,
 "originallyPublishedAt" timestamptz, "downloadEnabled" boolean, "commentsPolicy" integer,
 "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE "videoFile" (
 id integer PRIMARY KEY, "videoId" integer, "videoStreamingPlaylistId" integer,
 resolution integer NOT NULL, size bigint NOT NULL, extname text, filename text,
 fps integer, width integer, height integer);
CREATE TABLE "videoStreamingPlaylist" (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, "playlistFilename" text NOT NULL);
-- The modern layout has actor-side links above and no legacy thumbnail.type.
CREATE TABLE thumbnail (
 id integer PRIMARY KEY, filename text NOT NULL, "videoId" integer,
 "videoPlaylistId" integer, width integer, height integer);
CREATE TABLE storyboard (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, filename text NOT NULL,
 "totalHeight" integer NOT NULL, "totalWidth" integer NOT NULL,
 "spriteHeight" integer NOT NULL, "spriteWidth" integer NOT NULL,
 "spriteDuration" integer NOT NULL);
CREATE TABLE "videoCaption" (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, language text NOT NULL, filename text);
CREATE TABLE tag (id integer PRIMARY KEY, name text NOT NULL);
CREATE TABLE "videoTag" ("videoId" integer NOT NULL, "tagId" integer NOT NULL);
CREATE TABLE "videoComment" (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, "accountId" integer NOT NULL,
 "inReplyToCommentId" integer, text text NOT NULL, "deletedAt" timestamptz,
 "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE "videoPlaylist" (
 id integer PRIMARY KEY, "ownerAccountId" integer NOT NULL, name text NOT NULL,
 description text, privacy integer NOT NULL, type integer NOT NULL,
 "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE "videoPlaylistElement" (
 id integer PRIMARY KEY, "videoPlaylistId" integer NOT NULL, "videoId" integer,
 position integer NOT NULL);
CREATE TABLE "actorFollow" (
 id integer PRIMARY KEY, state text NOT NULL, "actorId" integer NOT NULL,
 "targetActorId" integer NOT NULL, url text);
CREATE TABLE "videoBlacklist" (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, reason text);
CREATE TABLE "videoChapter" (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, timecode integer NOT NULL, title text);
CREATE TABLE "accountVideoRate" (
 id integer PRIMARY KEY, "videoId" integer NOT NULL, "accountId" integer NOT NULL,
 type text NOT NULL, "createdAt" timestamptz NOT NULL DEFAULT '2026-10-16T00:00:00Z');
CREATE TABLE "actorImage" (
 id integer PRIMARY KEY, filename text NOT NULL, width integer, height integer,
 "actorId" integer NOT NULL, type integer NOT NULL);
