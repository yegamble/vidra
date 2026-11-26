# SizeTube recovery checks, November 26, 2026

| Check | Result |
| --- | --- |
| Nightly database and configuration | Passed. Both archives matched their expected SHA-256 digests on an independent recovery machine. The restored database had clean migration ledgers and matched the expected catalogue, search and moderation counts. |
| Historical video | Passed. The recovered original matched its source SHA-256 digest and decoded successfully. |
| Historical media inventory | In progress. Full-library recovery coverage remains open. |

Public traffic remains on the existing service pending the inventory result
and cutover acceptance.
