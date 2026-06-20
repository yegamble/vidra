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
});
