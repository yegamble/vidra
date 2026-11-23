# Choose the ATProto Personal Data Server

Set `ATPROTO_ENABLED=true` in the deployment env file to enable creator cross-posts. Provide a stable `ATPROTO_KEY_KEK`, generated with `openssl rand -base64 32`, or an existing federation encryption key. Preserve the key in the encrypted configuration backup.

| Admin selection | Deployment configuration | What starts |
| --- | --- | --- |
| Local Docker PDS | Leave `ATPROTO_PDS_URL` empty | Vidra starts an invite-only PDS and routes HTTPS to it at `pds.<site-host>`. |
| External PDS or entryway | Set `ATPROTO_PDS_URL` to its public HTTPS origin | New installations run only the Vidra services. The connection form shows the external origin. |

In a deployment with the ATProto setup options, run `vidra setup --template env/production.env.example --web` and choose the provider under **Optional → ATProto**. From the terminal, add `--atproto` to your setup command to enable cross-posting with the saved provider. A fresh installation defaults to local Docker and generates the credential-encryption key. Use `--atproto-pds local` to switch back to Docker or `--atproto-pds https://pds.example.org` to select a hosted service. Rerunning setup with no ATProto flags preserves the current choice. Apply changes with the normal deployment command.

For local hosting, create a DNS record for the PDS hostname pointing to the deployment before running `deploy/deploy.sh`. With external TLS termination, proxy that hostname to the loopback port 2583, or the port set in `ATPROTO_PDS_PORT`. The bundled Caddy provides the hostname route in managed TLS mode. Verify the service with `GET /xrpc/com.atproto.server.describeServer` at the PDS origin. Confirm its service DID and invitation requirement. Custom handles can resolve through their individual `_atproto` DNS TXT records.

Creators explicitly link an account using its app password. A changed default applies to new links. Migrate hosted accounts, identities and blobs before retiring a PDS whose endpoint existing links still use. Identity sign-in is configured separately with `ATPROTO_LOGIN_ENABLED`. [AT Protocol self-hosting and migration](https://atproto.com/guides/self-hosting)

## Storage and recovery

The service keeps its account and repository databases under `data/atproto-pds`. On first deployment Vidra creates a private `env/atproto-pds.env` containing the PDS rotation key, admin password and session-signing secret. Later deployments reuse it. The regular Vidra config archive includes this file. For a consistent filesystem backup, stop the PDS with `deploy/compose.sh stop pds`, snapshot or copy the data directory and its corresponding secret file, and start it again with `deploy/compose.sh start pds`. Restore both together. If the data directory already exists and the secrets are missing, deployment asks for the original file.

For S3-compatible PDS blob storage, remove `PDS_BLOBSTORE_DISK_LOCATION` from the PDS env file and set `PDS_BLOBSTORE_S3_BUCKET`, `PDS_BLOBSTORE_S3_REGION`, `PDS_BLOBSTORE_S3_ENDPOINT`, `PDS_BLOBSTORE_S3_ACCESS_KEY_ID` and `PDS_BLOBSTORE_S3_SECRET_ACCESS_KEY`. Set `PDS_BLOBSTORE_S3_FORCE_PATH_STYLE=true` for providers that require it. Use a dedicated bucket and credentials for the PDS. Select storage before the first creator upload. Changing these keys on a populated server requires migrating its existing blobs. Protect the blob bucket independently of the repository database backup. [Upstream PDS storage options](https://github.com/bluesky-social/atproto/blob/main/packages/pds/src/config/env.ts)
