import { expect, test, type Page } from "@playwright/test";

// Mocked studio coverage (a real backend is not running in `npm run ci`; the
// publish round-trip is proven in e2e-backed/studio.spec.ts).
const LOGIN = /\/api\/v1\/auth\/login$/;
const FEED = /\/api\/v1\/videos(\?|$)/;
const UNREAD = /\/api\/v1\/me\/notifications\/unread-count$/;
const MY_CHANNELS = /\/api\/v1\/me\/channels$/;
const CREATE_CHANNEL = /\/api\/v1\/channels$/;
const CREATE_VIDEO = /\/api\/v1\/channels\/ada_makes\/videos$/;
const UPLOAD = /\/api\/v1\/videos\/v1\/file$/;

function channel(handle: string, name: string) {
  return {
    id: "c1",
    owner_id: "u1",
    handle,
    display_name: name,
    description: "",
    follower_count: 0,
    created_at: new Date().toISOString(),
  };
}

const session = {
  token: "acc",
  refresh_token: "ref",
  token_type: "Bearer",
  expires_in: 900,
  user: {
    id: "u1",
    username: "ada",
    email: "ada@example.test",
    role: "user",
    email_verified: false,
    display_name: "Ada",
    bio: "",
    created_at: new Date().toISOString(),
  },
};

async function signIn(page: Page) {
  await page.route(LOGIN, (route) => route.fulfill({ json: session }));
  await page.route(FEED, (route) =>
    route.fulfill({ json: { videos: [], sort: "recent", limit: 20, offset: 0 } }),
  );
  await page.route(UNREAD, (route) => route.fulfill({ json: { unread_count: 0 } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("ada@example.test");
  await page.getByLabel("Password").fill("supersecret");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("the studio prompts anonymous viewers to sign in", async ({ page }) => {
  await page.goto("/studio");
  await expect(page.getByText("Sign in to use the studio")).toBeVisible();
});

test("a creator can create a channel", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) => route.fulfill({ json: { channels: [] } }));
  await page.route(CREATE_CHANNEL, (route) => {
    if (route.request().method() === "POST") return route.fulfill({ json: channel("ada_makes", "Ada Makes") });
    return route.fulfill({ json: { channels: [] } });
  });

  await page.getByRole("link", { name: "Studio" }).click();
  await expect(page.getByText("Create your first channel to start publishing.")).toBeVisible();
  await page.getByLabel("Channel handle").fill("ada_makes");
  await page.getByLabel("Channel display name").fill("Ada Makes");
  await page.getByRole("button", { name: "Create channel" }).click();

  // The new channel appears, and the upload form becomes available.
  await expect(page.getByRole("link", { name: /Ada Makes/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upload a video" })).toBeVisible();
});

test("a creator can upload and publish a video", async ({ page }) => {
  await signIn(page);
  await page.route(MY_CHANNELS, (route) =>
    route.fulfill({ json: { channels: [channel("ada_makes", "Ada Makes")] } }),
  );
  await page.route(CREATE_VIDEO, (route) =>
    route.fulfill({
      json: {
        id: "v1",
        channel_id: "c1",
        title: "My clip",
        description: "",
        privacy: "public",
        state: "draft",
        created_at: new Date().toISOString(),
      },
    }),
  );
  await page.route(UPLOAD, (route) =>
    route.fulfill({
      json: {
        video: {
          id: "v1",
          channel_id: "c1",
          title: "My clip",
          description: "",
          privacy: "public",
          state: "published",
          created_at: new Date().toISOString(),
        },
        file: {
          id: "f1",
          kind: "original",
          content_type: "video/mp4",
          original_name: "clip.mp4",
          size_bytes: 4,
          created_at: new Date().toISOString(),
        },
      },
    }),
  );

  await page.getByRole("link", { name: "Studio" }).click();
  await page.getByLabel("Video title").fill("My clip");
  await page.getByLabel("Video file").setInputFiles({
    name: "clip.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("test"),
  });
  await page.getByRole("button", { name: "Publish" }).click();

  await expect(page.getByText("Published!")).toBeVisible();
  await expect(page.getByRole("link", { name: /View .*My clip/ })).toBeVisible();
});
