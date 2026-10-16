# Published-image sealed-secret recovery subset

`published-sealed-recovery` is a dispatch-only workflow using two separate fresh
GitHub-hosted Ubuntu 24.04 VMs. Review the immutable tool commit and published
candidate record before dispatching it with `release=v0.7.8` and a 40-hex
`record_commit`. No workflow is dispatched by opening or merging these helpers.

The tool checkout uses the workflow's immutable `github.sha`. A separate checkout
reads record/preflight JSON at `record_commit`; it executes no metadata-checkout
code. Both SHAs are verified and recorded. The real PASS preflight must match the
release record's component commits, tags and image digests; the lane pulls the
recorded linux/amd64 digests and verifies running image revision labels.

The first VM unpacks the checksum-verified published bundle and runs its CLI to
generate a private configuration. Its backup/restore scripts remain unchanged.
Only the six image references and an internal Docker network are adapted in the
Compose input. Caddy configuration is generated for the backup, while the edge
service stays off. Local storage, closed registration and one newly generated
synthetic owner are required. There are no media uploads or object-store inputs.

This isolated fixture uses the current API container's private bridge address for
host probes and API controls. Docker may suppress published loopback mappings on
an internal network. Each control resolves the current running container again,
verifies its Compose ownership and membership in the owned internal bridge's
RFC1918 subnet, and supplies a matching explicit private-origin opt-in to the
Node helper. Redirects are refused and actual host port bindings must be absent.
All five service health checks and immutable image checks remain required. This
control route establishes no production port, DNS or browser-origin behavior.

The fixture enrolls TOTP, stores a dummy SMTP password targeting container
loopback port 1 with no listener, and stores a disabled OIDC provider with a dummy
client secret. External container delivery is blocked; the SMTP document itself
has no disabled mode. The source runs the shipped backup and stops its services.

Only `synthetic-handoff.age` crosses jobs. Its four exact members are a synthetic
DB dump, config archive, fixture login/TOTP state and bounded proof metadata.
No loose env file, real credential, GitHub token, runner home or raw log is an
artifact. The age identity in the support module is deliberately PUBLIC TEST
MATERIAL, distinct from generated application keys. It provides no confidentiality
against repository readers and must NEVER protect a real backup. The artifact
expires after one day; the destination verifies its source-job SHA-256 first.

The replacement VM must have a different kernel boot ID and no existing Vidra
tree, containers or volumes. Preinstalled Docker is explicitly allowed in this
hosted subset; the production blank-install guard is unchanged. Configuration is
restored before the database through the shipped restore script. Exact schema and
catalogue equality are checked before login modifies the TOTP replay ledger.
With a wrong MFA KEK, stored mail/OIDC credentials must be undecryptable and a
correct TOTP must fail. Restoring the original key must restore `secret_status=ok`
and successful MFA, while a wrong code remains refused.

Public verdict artifacts contain fixed status/boolean fields and immutable
release/tool/record provenance. Failed commands and raw API/container logs remain
private to the ephemeral VM. Failures export only fixed milestones, bounded HTTP
status codes and known-service state enums.

A green run is **published-image recovery evidence for synthetic sealed-secret
fixtures across two VMs**. It does not qualify fresh installation, real operator
data, offsite/provider durability, media recovery, REC-03 upgrade rollback,
RPO/RTO objectives, browser playback or the three-person stopwatch protocol.
