# Upgrade Vidra from its Git sources

Run these commands on the Docker host, in the deployment directory, as the install owner. The CLI equivalents are `vidra update --source --check` and `vidra update --source`. The latter shows the chosen release and asks before building. On an older install, first install a release containing both the snapshot manager and source updater using the published-image upgrade instructions. Both Git checkouts and release bundles use the same commands. To select a different configuration, export the same `ENV_FILE` you use for deployment.

```sh
python3 deploy/source-update.py check
python3 deploy/source-update.py apply
```

`check` compares your three configured component tags with the newest stable release recorded on the upstream Vidra main branch. It shows the exact Git commits that will be compiled. `--tag vX.Y.Z` selects a specific recorded release. Releases that predate the source overlay still use the existing `vidra update` image upgrade.

`apply` builds the three production Dockerfiles on this host. Reserve enough scratch space, Docker storage and memory for the Go and frontend toolchains. The built image IDs can differ between hosts as the Dockerfiles pull updated base layers. The source tags must resolve to the commits in the published release record. The core build uses the same yt-dlp pin as its tagged release workflow. Both migration binaries must report the recorded maximum schema version.

Before updating the checkout or installed pins, the command takes a full `pre-upgrade` snapshot using the configured install snapshot repository. Configure and test that repository before the first source upgrade. Follow the [snapshot guide](SNAPSHOTS.md) to list snapshots or restore the saved install. Building happens before the snapshot, while the current release can keep serving visitors. The snapshot procedure may pause service during capture.

The production deploy then performs its own pre-deploy database dump, dependency image pull, two gated migrations, start and health probes. The API, worker, frontend, search and both migrators use local image names containing their configuration digests. Compile-time or snapshot failure leaves the configured version in place. The recovery command and full snapshot ID are printed immediately before pinning. Use the same `source-update.py apply` entry point for future source releases. `python3 deploy/source-update.py verify` checks the effective Compose references, tags, image identities and available component checkouts.

Source mode uses the bundled PostgreSQL ledgers for its schema checks. A target behind either ledger requires the snapshot restore path. BuildKit, Git, Python, Docker Compose with the production overlay features, and read access to the public Vidra Git repositories are required. Source images live on the deployment host. Keep the install snapshots that contain those images for each recovery point you want to retain.
