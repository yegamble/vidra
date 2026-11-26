# SizeTube recovery checks, November 26, 2026

Results as of 05:06 UTC.

| Check | Result |
| --- | --- |
| Nightly database and configuration | Passed. Both archives matched their expected SHA-256 digests on an independent recovery machine. The restored database had clean migration ledgers and matched the expected catalogue, search and moderation counts. |
| Video recovery | Both video restore checks passed. The historical original matched its source SHA-256 digest and decoded successfully. |
| Historical media inventory | In progress. The recovery inventory matched 240,869 of 251,042 historical file versions. All comparable checksums matched. The 10,173 outstanding versions included files still current on the source. |

Public traffic remains on the existing service pending the inventory result
and cutover acceptance.
