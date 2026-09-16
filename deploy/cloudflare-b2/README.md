# Authenticated Backblaze delivery through Cloudflare

This optional Worker provides a path-style S3 endpoint for Vidra. It verifies
the client's AWS SigV4 signature, limits access to one bucket, then signs the
same operation against that bucket's regional Backblaze endpoint. Reads stream
**B2 → Cloudflare → client**, including API/worker reads and signed browser GETs.
Application images and object keys do not change.

Use an existing private media bucket and its bucket-scoped application key.
Never expose a private bucket through a Worker that signs anonymous requests.
This Worker rejects unsigned, expired and tampered requests, other buckets,
bucket creation/deletion, and unsupported streaming-signature formats. Normal
TLS SigV4 uploads and multipart operations are supported. Bodies are streamed,
not buffered into Worker memory. Cloudflare's per-request upload limits still
apply; use multipart parts below the account's limit.

## Deployment

1. In this directory, run `npm ci --ignore-scripts` and `npm test`.
2. Copy `wrangler.example.jsonc` to ignored `wrangler.jsonc`; fill in the
   account, custom hostname, bucket, B2 endpoint and region. The custom hostname
   should be dedicated to S3 traffic. Do not point it at the Vidra API.
3. Store the bucket-scoped key ID as Worker secret `ACCESS_KEY` and its secret
   as `SECRET_KEY`, using Wrangler secrets or the Cloudflare API. Do not put
   either value in the checked-in configuration. They must match Vidra's
   `STORAGE_S3_ACCESS_KEY` and `STORAGE_S3_SECRET_KEY`.
4. Deploy using Wrangler. Alternatively, bundle `worker.mjs` as ESM and upload
   it with the Workers API; retain the MIT notices from `aws4fetch`. Disable
   workers.dev previews and request logging: signed URLs are credentials.
5. Before switching Vidra, use an independent S3 client against the custom
   hostname to verify HEAD bucket/object, PUT, ranged GET, signed GET, multipart
   completion/readback, listing and deletion of a generated test object. Check
   unsigned direct B2 and Worker requests are denied. `CF-Ray` and
   `X-Vidra-Storage-Route: cloudflare-b2` on a successful read identify the route.
6. Back up the production environment, set `STORAGE_S3_ENDPOINT` to the custom
   hostname, retain `STORAGE_S3_USE_SSL=true` and `STORAGE_S3_FORCE_PATH_STYLE=true`,
   then use `deploy/deploy.sh`. It retains the pre-deploy dump, discrete migrations
   and readiness gates. Enable the admin setting `delivery_presign_enabled` so
   eligible public media uses signed Cloudflare URLs. Vidra's existing access
   checks still govern private media. Verify with Vidra's own SDK and player.

This is distinct from `DELIVERY_CDN_BASE_URL`, whose origin is the Vidra API.
No shared caching is enabled here: every request must pass authentication and
every object response is `private, no-store`. That preserves signed URL expiry
and avoids private data persisting in an independently accessible edge cache.
The benefit is the Cloudflare transfer path even on cache misses. Add shared
caching only with an explicit authorization and global invalidation design.

Signed URLs are bearer credentials. Vidra v0.6.6 issues them for one hour;
making a video private stops new public redirects but does not revoke a URL
already issued. The Worker enforces its original expiry. Deployments requiring
immediate privacy revocation should leave `delivery_presign_enabled` off:
Vidra then checks access on each media request and reads B2 through the same
Cloudflare endpoint, with the additional API-server bandwidth cost.

Cloudflare Browser Integrity Check can reject non-browser test user agents
before the Worker runs (error 1010). Distinguish that from a Worker/B2 denial;
test real browser and application user agents, and scope any necessary zone
configuration adjustment to this hostname rather than disabling protection
globally.

## Cost and IPFS boundary

Backblaze documents free B2-to-Cloudflare transfer through its
[private-bucket integration](https://www.backblaze.com/docs/cloud-storage-deliver-private-backblaze-b2-content-through-cloudflare-cdn).
This does not make storage, API transactions or Workers CPU/requests free.
Use an appropriate paid Developer Platform service for video delivery; verify
the account's subscriptions and [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/),
separately from the zone's website plan. Account billing is the final evidence
of charges; a successful request is evidence of the network route.

IPFS workers that read Vidra's configured S3 backend also use this endpoint.
That lowers transfer cost but does not provide pin storage. Keep bulk pinning
off until capacity and a bounded publication policy are ready. Only eligible
public media should be published globally.

## Recovery and verification scope

Back up the deployed Worker source/configuration, bucket credentials in the
existing private environment backup, and the pre-change environment. Roll back
by restoring the original regional B2 `STORAGE_S3_ENDPOINT` and deploying through
`deploy/deploy.sh`; reads then use direct B2 transfer pricing. Disable the signed
delivery setting if browser delivery also needs to revert. Rotate the key in
both Vidra and the Worker together.

`npm test` checks signature rejection, range preservation, presigned response
parameters, streamed multipart bodies and bucket-delete refusal. It is a
separate operator check, not a claim that the meta repo's existing boot CI
exercises Cloudflare or Backblaze. A live independent SDK test and a Vidra
runtime check are required before switching a deployment.
