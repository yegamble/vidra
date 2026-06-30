import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, videoOriginalUrl, videoThumbnailUrl } from "./endpoints";

function okJson(): Response {
  return new Response(JSON.stringify({}), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("api endpoints", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(okJson());
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function calledUrl(): string {
    return (fetchMock.mock.calls[0] as [string])[0];
  }

  it("getFeed targets the feed with sort + pagination", async () => {
    await api.getFeed({ sort: "trending", limit: 10 });
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/videos?sort=trending&limit=10");
  });

  it("searchVideos encodes the query", async () => {
    await api.searchVideos("go lang");
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/videos/search?q=go+lang");
  });

  it("getChannel encodes the handle in the path", async () => {
    await api.getChannel("ada makes");
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/channels/ada%20makes");
  });

  it("getVideo targets the detail endpoint", async () => {
    await api.getVideo("v1");
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/videos/v1");
  });

  it("media URL helpers build direct stream/poster URLs", () => {
    expect(videoOriginalUrl("v1")).toBe("http://localhost:8080/api/v1/videos/v1/original");
    expect(videoThumbnailUrl("v1")).toBe("http://localhost:8080/api/v1/videos/v1/thumbnail");
  });

  it("getWatchHistory targets the history endpoint with pagination", async () => {
    await api.getWatchHistory({ limit: 5 });
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/me/history?limit=5");
  });

  it("recordWatchProgress PUTs the position to the watch-progress endpoint", async () => {
    await api.recordWatchProgress("v1", 42);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/videos/v1/watch-progress");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ position_seconds: 42 });
  });

  it("getWatchProgress targets the watch-progress endpoint", async () => {
    await api.getWatchProgress("v1");
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/videos/v1/watch-progress");
  });

  it("deleteHistoryEntry DELETEs a single history entry", async () => {
    await api.deleteHistoryEntry("v1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/me/history/v1");
    expect(init.method).toBe("DELETE");
  });

  it("clearWatchHistory DELETEs the whole history", async () => {
    await api.clearWatchHistory();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/me/history");
    expect(init.method).toBe("DELETE");
  });

  it("getNotifications targets the inbox with the unread filter", async () => {
    await api.getNotifications({ unread: true, limit: 10 });
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/me/notifications?unread=true&limit=10");
  });

  it("getUnreadNotificationCount targets the count endpoint", async () => {
    await api.getUnreadNotificationCount();
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/me/notifications/unread-count");
  });

  it("markNotificationRead POSTs to the per-notification read endpoint", async () => {
    await api.markNotificationRead("n1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/me/notifications/n1/read");
    expect(init.method).toBe("POST");
  });

  it("markAllNotificationsRead POSTs to the read-all endpoint", async () => {
    await api.markAllNotificationsRead();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/me/notifications/read-all");
    expect(init.method).toBe("POST");
  });

  it("getMyPlaylists targets the playlists endpoint", async () => {
    await api.getMyPlaylists();
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/me/playlists");
  });

  it("createPlaylist POSTs the body to /playlists", async () => {
    await api.createPlaylist({ title: "Faves", visibility: "public" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/playlists");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ title: "Faves", visibility: "public" });
  });

  it("getPlaylist targets the detail endpoint", async () => {
    await api.getPlaylist("p1");
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/playlists/p1");
  });

  it("updatePlaylist PATCHes the playlist", async () => {
    await api.updatePlaylist("p1", { title: "Renamed" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/playlists/p1");
    expect(init.method).toBe("PATCH");
  });

  it("deletePlaylist DELETEs the playlist", async () => {
    await api.deletePlaylist("p1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/playlists/p1");
    expect(init.method).toBe("DELETE");
  });

  it("addToPlaylist POSTs the video id", async () => {
    await api.addToPlaylist("p1", "v1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/playlists/p1/videos");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ video_id: "v1" });
  });

  it("removeFromPlaylist DELETEs the item", async () => {
    await api.removeFromPlaylist("p1", "v1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/playlists/p1/videos/v1");
    expect(init.method).toBe("DELETE");
  });

  it("getMyChannels targets the channels endpoint", async () => {
    await api.getMyChannels();
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/me/channels");
  });

  it("createChannel POSTs the body to /channels", async () => {
    await api.createChannel({ handle: "ada_makes", display_name: "Ada Makes" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/channels");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ handle: "ada_makes", display_name: "Ada Makes" });
  });

  it("createVideoDraft POSTs to the channel's videos endpoint", async () => {
    await api.createVideoDraft("ada_makes", { title: "Hi", privacy: "public" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/channels/ada_makes/videos");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ title: "Hi", privacy: "public" });
  });

  it("reportVideo POSTs the reason to the video report endpoint", async () => {
    await api.reportVideo("v1", "spam");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/videos/v1/report");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ reason: "spam" });
  });

  it("reportComment POSTs the reason to the comment report endpoint", async () => {
    await api.reportComment("c1", "abuse");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/comments/c1/report");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ reason: "abuse" });
  });

  it("updateVideo PATCHes the metadata to the video endpoint", async () => {
    await api.updateVideo("v1", { title: "New title", privacy: "unlisted" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/videos/v1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ title: "New title", privacy: "unlisted" });
  });

  it("deleteVideo DELETEs the video", async () => {
    await api.deleteVideo("v1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/videos/v1");
    expect(init.method).toBe("DELETE");
  });

  it("uploadVideoFile POSTs multipart form data (no JSON content-type)", async () => {
    const file = new File(["x"], "clip.mp4", { type: "video/mp4" });
    await api.uploadVideoFile("v1", file);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }];
    expect(url).toBe("http://localhost:8080/api/v1/videos/v1/file");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
    expect(init.headers["content-type"]).toBeUndefined();
  });

  it("getReports defaults to all reports (no status filter)", async () => {
    await api.getReports();
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/admin/reports");
  });

  it("getReports adds status=open when openOnly is set", async () => {
    await api.getReports({ openOnly: true, limit: 100 });
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/admin/reports?status=open&limit=100");
  });

  it("resolveReport POSTs the status + note to the resolve endpoint", async () => {
    await api.resolveReport("r1", { status: "accepted", note: "spam" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/admin/reports/r1/resolve");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ status: "accepted", note: "spam" });
  });

  it("getAdminUsers targets the admin users endpoint with the q filter", async () => {
    await api.getAdminUsers({ q: "ada", limit: 100 });
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/admin/users?q=ada&limit=100");
  });

  it("getAdminUsers omits q when not provided", async () => {
    await api.getAdminUsers();
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/admin/users");
  });

  it("updateAdminUser PATCHes the role / active flag", async () => {
    await api.updateAdminUser("u1", { role: "moderator", is_active: false });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/admin/users/u1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ role: "moderator", is_active: false });
  });

  it("getBlockedVideos targets the block-list endpoint with pagination", async () => {
    await api.getBlockedVideos({ limit: 100 });
    expect(calledUrl()).toBe("http://localhost:8080/api/v1/admin/videos/blocked?limit=100");
  });

  it("unblockVideo DELETEs the block for the video", async () => {
    await api.unblockVideo("v1");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/admin/videos/v1/block");
    expect(init.method).toBe("DELETE");
  });

  it("blockVideo POSTs the block with the reason", async () => {
    await api.blockVideo("v1", { reason: "copyright" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8080/api/v1/admin/videos/v1/block");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ reason: "copyright" });
  });
});
