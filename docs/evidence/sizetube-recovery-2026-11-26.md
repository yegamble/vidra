# SizeTube recovery checks, November 26, 2026

**Media recovery remains open.** The 15:00 UTC comparison matched 240,870 of
251,042 historical upload versions. The remaining 10,172 versions totaled
260,363,280,859 bytes. Public traffic remains on PeerTube pending full media
recovery, reconciliation against the frozen production source and cutover acceptance.

| Time (UTC) | Check | Result |
| --- | --- | --- |
| 04:35 | Separate-host database and configuration restore | Passed. On the operator's Mac, the operator-held recovery key opened the encrypted recovery credentials. Both off-site archives from the November 25 19:08 UTC backup matched their expected SHA-256 digests. The restored database had clean migration ledgers and matched the expected catalogue, search and moderation counts. |
| 04:43 and 04:50 | Historical video restores | Passed for two distinct samples at their original paths. The recovery copies matched the source SHA-256 digests and each decoded three frames. The restores took 5.16 and 0.68 seconds, respectively. |
| 05:06 | Earlier historical inventory | 240,869 of 251,042 versions matched. The 10,173 outstanding versions included files still current on the source. |
| 14:56 | Older private upload | The recovery account held 13 of 15 streaming objects. The source reported both outstanding objects as pending. An earlier playback control used the source for those two objects. Destination-only playback remains open. |
| 14:57 | Separate synthetic upload | Passed. All seven recovery objects matched their source SHA-256 digests. An independent offline rebuild reproduced the published directory content identifier (CID) using the recovery copies. Three decoded frames matched after a four-second seek. |
| 15:00 | Historical inventory | 240,870 versions matched by name, original upload time and length, with zero checksum mismatches where comparable. All matched versions had the expected encryption and governance retention. Of those, 13,843 had no comparable checksum and 173,763 matched a provider checksum marked unverified. |

The recovery inventory must account for every historical upload version and
preserve source visibility, then cover subsequent versions through its recorded
cutoff. The older private upload must also decode using only the recovery
account. The final frozen-source import, acceptance checks and traffic switch
remain pending. [SizeTube cutover checklist](../sizetube-cutover-checklist.md#d12-media-recovery-and-backup-monitoring)
