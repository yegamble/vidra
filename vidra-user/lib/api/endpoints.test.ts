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
});
