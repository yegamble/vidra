# Outbound email — why it fails on a VPS, and how to configure it

**Status (2026-09-20).** The admin-panel email configuration described in
[Two places mail can be configured](#two-places-mail-can-be-configured) is being merged to
`main` in `vidra-core` and `vidra-user`; it ships in the **first releases of those components
after core v0.7.5**. Until you run those releases, the environment keys are the only way to
configure mail and the rest of this doc still applies to them. Every provider request shape was
verified against the vendor's own published API documentation and against local test servers —
**nothing here was exercised against a live vendor API**, so treat provider quotas, prices and
regional behaviour as things to confirm on the vendor's page before you commit to one.

## The problem

Most VPS hosts block outbound SMTP so their address space cannot be used to send spam, and the
three ports mail submission actually uses — 25, 465 and 587 — are exactly the ones they block.
DigitalOcean, the most common Vidra host, blocks all three on every Droplet with no documented
appeal, so a Vidra that tries to talk SMTP from the machine simply hangs and your
password-reset and verification mail never leaves. Nothing in this table documents a block on
port 2525 or on 443, which is why an HTTPS API transport works everywhere and an SMTP transport
does not.

✖ = blocked by default · ✔ = open by default

| Host | 25 | 465 | 587 | 2525 / 443 | Can it be lifted? |
|---|---|---|---|---|---|
| **DigitalOcean** | ✖ | ✖ | ✖ | not mentioned | **No appeal path is documented.** "SMTP ports 25, 465, and 587 are blocked on Droplets"; the block applies to **all Droplets by default and includes traffic passing through a Reserved IP address**. DigitalOcean instead recommends "using a third-party email as a service provider" and "strongly recommend[s] against running your own mail server". Doc updated 2026-07-13. ([docs](https://docs.digitalocean.com/support/why-is-smtp-blocked/)) |
| Hetzner Cloud | ✖ | ✖ | ✔ | ✔ | Limit request in the console after ~1 month and a first paid invoice, reviewed case by case. Port 587 needs no request. ([docs](https://docs.hetzner.com/cloud/servers/faq/)) |
| Vultr | ✖ | ✔ | ✔ | ✔ | Support ticket describing the use case; "reviewed case-by-case and not guaranteed". ([docs](https://docs.vultr.com/support/products/compute/why-is-smtp-blocked)) |
| Linode / Akamai | ✖ | ✖ | ✖ | ✔ | Only "for some new accounts created after November 5th, 2019"; lifted by a support request with use case, domains and rDNS. ([docs](https://techdocs.akamai.com/cloud-computing/docs/send-email)) |
| AWS EC2 / Lightsail | throttled | ✔ | ✔ | ✔ | "Request to remove email sending limitations" form, per region. ([re:Post](https://repost.aws/knowledge-center/ec2-port-25-throttle)) |
| GCP Compute | ✖ | ✔ | ✔ | ✔ | Port 25 to external destinations is blocked outright; "Google Cloud does not place any restrictions on traffic sent to external destination IP addresses using destination TCP ports 587 or 465". ([docs](https://docs.cloud.google.com/compute/docs/sending-mail)) |
| Azure VMs | ✖ except Enterprise Agreement / MCA-E | ✔ | ✔ | ✔ | "Using these email delivery services on authenticated SMTP port 587 isn't restricted in Azure, regardless of the subscription type." ([docs](https://learn.microsoft.com/en-us/azure/virtual-network/troubleshoot-outbound-smtp-connectivity)) |
| Scaleway | ✖ | ✖ | ✖ | ✔ | **Self-service** — tick "Enable SMTP" on the Instance's security group. ([docs](https://www.scaleway.com/en/docs/instances/how-to/send-emails-from-your-instance/)) |
| Oracle Cloud | ✖ | ✔ | ✔ | ✔ | Tenancies created after 2021-06-23 only; service-limit increase request for an exemption. ([release note](https://docs.oracle.com/en-us/iaas/releasenotes/changes/f7e95770-9844-43db-916c-6ccbaf2cfe24)) |
| OVHcloud | unverified | ✔ | ✔ | ✔ | OVH's own guides and community answers contradict each other on the port-25 default, so we do not state one. What is documented: the anti-spam system re-blocks 25 after abuse, and a third strike can be permanent. ([docs](https://docs.ovhcloud.com/en/guides/bare-metal-cloud/dedicated-servers/antispam-best-practices)) |

Two things this table does **not** license you to promise anyone:

- **DigitalOcean unblocking on request.** Community answers claim a case-by-case review; the
  official doc documents no appeal process at all. Plan as if there is none.
- **OVHcloud's port-25 default.** Deliberately left as "unverified" above rather than guessed;
  test it on your own server before you rely on it.

## Two places mail can be configured

**(a) The environment** — `MAIL_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM` in `env/production.env`. Unchanged, still supported, still the
right answer for an operator who configures the host from files. Generic SMTP only.

**(b) Admin → Configuration → Email** — a form in the running instance: pick a transport
(generic SMTP, or one of the HTTPS API providers below), enter the credentials, send a test
mail, save. No redeploy, no restart; the change reaches every process within about ten seconds.
This is the only way to use an API transport.

### Precedence

**A saved panel configuration wins over the environment.** The environment keys are the
fallback, used when nothing is saved in the panel. The panel's **"Use environment
configuration"** action deletes the saved configuration and hands mail back to the environment
keys — it does not clear them, and it does not turn mail off if they are set. The panel shows
which of the two is live, so a machine whose `SMTP_HOST` looks right but whose mail goes
somewhere else is answered by looking at that line, not by re-reading the env file.

### Credentials entered in the panel are sealed

Passwords and API keys entered in the panel are stored **encrypted with the same key-encryption
chain as MFA secrets** (`MFA_KEY_KEK`, falling back to `FEDERATION_KEY_KEK`). Three consequences
worth knowing before you start typing:

- **No KEK means the panel refuses to store the credential.** It fails closed rather than
  writing a secret in the clear — saving is rejected with an explicit error, not silently
  degraded. An SMTP configuration with no password can still be saved. If you want to configure
  mail from the panel, set `MFA_KEY_KEK` first.
- **Rotating the KEK does not take the app down.** The stored credential simply becomes
  undecryptable: the instance keeps running, the panel says the secret is undecryptable, and
  sends fail with the reason `secret_undecryptable`. The fix is to re-enter the credential —
  there is nothing to restore and no outage to ride out.
- Secrets are never echoed back. The panel shows "saved" and offers to replace, and the API
  never returns a stored password or key.

### `MAIL_ENABLED` and refusing to boot

`MAIL_ENABLED=true` **requires** `SMTP_HOST` and `SMTP_FROM`; the api refuses to boot in
production without them. So an operator who intends to configure mail **only** from the admin
panel must set `MAIL_ENABLED=false` in `env/production.env` — otherwise the instance will not
start far enough for the panel to exist. Setting it false does not disable mail once a panel
configuration is saved; the saved configuration wins.

## Choosing a transport

### API providers (first class)

These four talk HTTPS on port 443, which no host in the table above blocks, and each maintains
the sending IP reputation for you. Figures checked 2026-09-20 from the vendor's own pricing
page — confirm before committing, vendors change these.

| Provider | Free tier | EU option | Signup friction |
|---|---|---|---|
| **Resend** | 3,000/month, capped at **100/day** ([pricing](https://resend.com/pricing)) | **Unverified.** Resend's pricing page says only "multi-region"; third-party sources claim sending from Ireland with account data in the US, which we could not confirm from Resend's own docs. Do not choose it *for* EU residency. | Lowest of any provider here |
| **Brevo** | **300/day, no expiry** ([pricing](https://www.brevo.com/pricing/)) | French company, EU-hosted | Low; occasional account review |
| **Mailgun** | 100/day ([pricing](https://www.mailgun.com/pricing/)) | **Yes** — a genuine EU region (`api.eu.mailgun.net`); Mailgun states data "can remain in the region of your choice" | DNS domain verification, card on file |
| **Postmark** | 100/month, "never expires" ([pricing](https://postmarkapp.com/pricing)) | Not documented | Manual review that your use is transactional |

Rules of thumb: **Resend** if you want it working in five minutes; **Brevo** if the instance
must stay on a free tier forever and 300 mails a day is enough; **Mailgun** if you need
documented EU residency; **Postmark** if the instance sends only verification and
password-reset mail — its free tier is monthly rather than daily, and its signup review is
aimed at exactly that transactional-only use. We deliberately do not rank these by
deliverability: no primary source supports ordering providers by inbox placement, and anyone
who tells you otherwise is quoting a vendor's marketing.

Amazon SES and SendGrid are **not** first-class transports yet. SES is reachable today through
the generic SMTP transport, and AWS documents alternate submission ports for exactly this
situation: STARTTLS on 25, 587 **or 2587**, implicit TLS on 465 **or 2465**
([SES SMTP docs](https://docs.aws.amazon.com/ses/latest/dg/smtp-connect.html)) — take the
regional endpoint hostname from the SES console. SendGrid retired its free plans in 2025
([Twilio changelog](https://www.twilio.com/en-us/changelog/sendgrid-free-plan)), so it is a poor
default for this class of operator regardless.

### When plain SMTP is still fine

Use SMTP when either is true:

- **Port 587 is open on your host** (Hetzner, Vultr, GCP, Azure, AWS, Oracle in the table
  above) and you already have a relay — your own mail server, a workplace relay, or a provider's
  SMTP endpoint.
- **Your provider listens on a port nobody filters** — 2525 or 2587. This is the escape hatch
  for DigitalOcean, Linode-restricted accounts and Scaleway if you insist on SMTP.

Vidra's SMTP transport makes the encryption mode explicit rather than guessing: `starttls`
(required — the send fails if the server does not offer it), `tls` (implicit TLS, port 465) or
`none`. There is no "skip certificate verification" option and there will not be one.

Settings we have confirmed from the vendor's own documentation:

| Provider | Host | Port | Encryption | Source |
|---|---|---|---|---|
| Resend | `smtp.resend.com` | 2587 (also 25, 587, and 465/2465 for implicit TLS) | STARTTLS; username `resend`, password = the API key | [Resend SMTP docs](https://resend.com/docs/send-with-smtp) |
| Brevo | `smtp-relay.brevo.com` | 587 | STARTTLS; the credential is an **SMTP key**, not your account password | Brevo's own docs, read 2026-09-20. Their help centre refuses automated requests, so the link is omitted rather than cited blind — the same values are shown in your Brevo dashboard. |
| SMTP2GO | `mail.smtp2go.com` | **2525** (also 8025, 587, 80; implicit TLS on 465, 8465, 443) | STARTTLS | [SMTP settings](https://support.smtp2go.com/hc/en-gb/articles/223087627-SMTP-Settings) — documented as open "at almost all locations". The page returns 403 to automated checks; open it in a browser. |

SMTP host/port settings for **Mailgun, Postmark, Mailjet, MailerSend, Mailtrap, ZeptoMail and
Scaleway TEM** are widely repeated online but **unverified — check the vendor's docs** (or your
dashboard, which is authoritative for your account) before entering them.

## DNS: SPF, DKIM and DMARC

Picking a provider gets the mail out of the machine. DNS is what gets it into an inbox.

- **SPF** — a TXT record on your sending domain authorising your provider's servers. Your
  provider gives you the exact value.
- **DKIM** — a key the provider publishes for you to add as a TXT/CNAME record; it signs each
  message so the recipient can prove it was not altered.
- **DMARC** — a TXT record at `_dmarc.yourdomain` telling receivers what to do when SPF and
  DKIM disagree with your From: domain. Start at `v=DMARC1; p=none; rua=mailto:you@yourdomain`
  and tighten once the reports are clean.

Gmail has required of **every** sender since 2024-02-01: SPF **or** DKIM, valid forward and
reverse DNS, a TLS connection, RFC 5322-conformant messages, and a spam rate under 0.3%. The
stricter rules — SPF **and** DKIM, DMARC, From:-domain alignment, one-click unsubscribe — apply
only to senders of **5,000 or more messages a day to Gmail**
([Gmail sender guidelines](https://support.google.com/mail/answer/81126?hl=en)). A Vidra
instance for a small community will never cross that line, so the bulk rules do not bite — but
the all-sender rules do, and **a bare VPS fails them**: the IP has no sending history, no
reverse DNS you control, and sits in a netblock other tenants' spam has already tainted. That
is the real reason not to send direct-to-MX from the machine, independent of which ports the
host blocks. A provider gives you a warmed IP and the SPF/DKIM records that make your From:
domain legitimate; you still have to publish them.

## Troubleshooting

The panel's test send reports a machine-readable reason. Read it before changing anything.

| Reason | What it means | What to do |
|---|---|---|
| `connect_failed` or `timeout` on port **25, 465 or 587** | Nothing answered, or the connection hung. On a VPS this is almost always the host's outbound block, not a wrong hostname. | Check your host in the table above. On DigitalOcean, all three ports are blocked and there is no appeal: switch to an API provider, or to an SMTP endpoint on 2525/2587. |
| `connect_failed` or `timeout` on another port | Wrong host, wrong port, or a firewall of your own. | Verify host and port against the provider's dashboard; check the droplet's egress rules. |
| `tls_failed` | The server did not offer STARTTLS (and the mode requires it), or the certificate did not verify. | Confirm the encryption mode matches the port: 465 is implicit `tls`, 587/2525/2587 are `starttls`. A self-signed relay certificate will fail, by design. |
| `auth_failed` | The credential was rejected. | Most providers want an **API key or SMTP key**, not your account password (Brevo, Resend, SES all do). Re-copy the key; check you are not using a sandbox/test key against the live endpoint. |
| `sender_rejected` | The provider accepted your credential but refused the `From:` address. | The sending domain is not verified yet, or the address is not an allowed sender. Finish the provider's domain verification (SPF/DKIM records) and use a From: address on that domain. |
| Mailgun: "domain not found in this region" | Your Mailgun domain lives in one region and you selected the other. | Mailgun's US and EU stacks are separate. Flip the region field to match where the domain was created. |
| `rate_limited` | Free-tier daily/monthly cap, or a provider throttle. | Check the day's volume against the free tiers above; a fresh account is also throttled while it warms up. Vidra separately limits **test** sends to 10 per hour per admin, so a long configuration session can hit that instead. |
| `secret_undecryptable` | The stored credential can no longer be decrypted — the KEK (`MFA_KEY_KEK` / `FEDERATION_KEY_KEK`) changed or was lost. | Re-enter the credential in the panel. Nothing else is broken; the app is running normally. |
| Saving refused, no KEK | No key-encryption key is set, so there is nowhere safe to put the secret. | Set `MFA_KEY_KEK` in `env/production.env` and redeploy, then save again. |

If mail works from the panel's test send but users still report nothing arriving, the problem is
DNS or reputation, not transport: check SPF/DKIM for the From: domain, and look in the
provider's own delivery log, which tells you whether the recipient bounced or filtered it.
