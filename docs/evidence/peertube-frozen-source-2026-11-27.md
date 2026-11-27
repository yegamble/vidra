# Frozen PeerTube source recovery rehearsal, November 27, 2026

The recovery exercise covered two separate questions. A new cloud guest verified that the saved source disk contained the frozen database and local artwork. A local test then exercised PeerTube's cold-start procedure with synthetic data. The public Vidra origin and the incumbent PeerTube server remained in place.

| Check | Observed result |
| --- | --- |
| Cloud disk restore | The provider completed creation from the private image in an isolated VPC. The applied firewall allowed only operator SSH and had zero outbound rules. |
| Frozen database | All 91 tables and 5,379,895 rows matched the pre-existing frozen physical fingerprint. The visibility digest matched for 15,748 local videos, including 13,890 eligible public videos. The 218,537,930-byte frozen export matched its original SHA-256 and passed a table-of-contents read. |
| Local artwork | The restored bytes matched independent source hashes for five avatars, five thumbnails and five storyboards. These were samples across the local collections. |
| Cloud write protection | All 27 scoped queues remained paused with zero active work. A new application-role connection rejected a zero-row update with SQLSTATE `25006`. nginx refused POST with 503 and `Retry-After: 3600`. |
| Cloud cold boot | A loopback configuration GET returned 502. PeerTube's `createFunctions` startup step reached `CREATE FUNCTION` while its database role was read-only. The test guest was destroyed with the original role fence intact. |
| Same-version local cold start | The official linux/arm64 `chocobozzz/peertube:v8.3.1-trixie` filesystem, manifest `sha256:2ae02be3da04eaff0e95a6bd45a57917edb7bf150f8db7276f65a10603ddf29e`, reproduced the startup error with PostgreSQL 18. Allowing initialization in the disposable database, restoring the role setting and draining pre-fence sessions took 13.3 seconds. |
| Local verification after the role was restored | The 8.3.1 API returned 200. A real client stylesheet returned 206 for bytes 0–127. A fresh application-role connection rejected the zero-row update with SQLSTATE `25006`. Zero older pool connections remained, and the synthetic account and video counts matched. |
| Containment and teardown | The local lab shared a loopback-only network namespace, had no published ports or SMTP transport, and held all 31 queues paused with zero active or completed jobs. The temporary cloud guest, firewall, VPC, tag and local fixture containers were removed. The retained image and production DNS were verified afterward. |

The cloud proof covers the saved database and sampled local artwork. The role-transition result covers the same PeerTube version in a synthetic ARM64 lab. The stylesheet request covers local HTTP ranges. External media restoration and rollback of writes made after cutover have their own acceptance records. [Frozen-source recovery procedure](../peertube-frozen-source-recovery.md)
