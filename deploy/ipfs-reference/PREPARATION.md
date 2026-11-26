# Prepare a native HLS reference manifest

Prepare one publicly eligible Vidra video for operator review. The command reads PostgreSQL and the configured media bucket, then writes a verified candidate manifest to standard output. A candidate becomes an active approval only when an operator installs it in the origin's manifest directory.

## Service access

Run the command on a trusted operator host with Python 3, Botocore and the PostgreSQL client `psql`. Configure the usual `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and a protected `PGPASSFILE` for a role that can select from `public.ipfs_public_reference_videos`. The view must return a single eligible native HLS generation for the requested UUID.

Supply the source bucket's read-only S3 credentials through the process environment using `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and, for temporary credentials, `AWS_SESSION_TOKEN`. The source must support immutable VersionIds, HEAD on current objects and ranged GET on specific versions. The command uses the same fixed HTTPS path-style endpoint and region as the origin.

## Prepare the candidate

1. Set `staging_dir` to a private directory outside the origin's active manifest directory.
2. Set `video_uuid` to the lowercase Vidra video UUID. Set `s3_endpoint`, `media_bucket` and `s3_region` to the configured media storage location.
3. Run the following command from the repository root.

```sh
umask 077
python3 deploy/ipfs-reference/prepare.py \
  --video "$video_uuid" \
  --endpoint "$s3_endpoint" \
  --bucket "$media_bucket" \
  --region "$s3_region" > "$staging_dir/$video_uuid.candidate.json"
```

Check the exit status before reviewing the file. Successful output includes the video UUID, generation master key and each referenced object's exact S3 VersionId, length, SHA-256 and opaque origin ID. A failed command may leave an empty file created by the shell redirection.

The preparer starts at the native generation master, follows its HLS references and reads each immutable object in 4 MiB ranges to compute the full-file hash. It recognizes Vidra's native MPEG-TS and CMAF VOD outputs, including audio and I-frame playlists. It rejects external URIs, encryption, unsupported tags, unfinished streams and references to progressive downloads. It checks every current version again and re-reads the public-generation view before emitting the manifest.

The default budget is 16 GiB of media payload and one hour per invocation. `--max-bytes` and `--max-seconds` change these limits. Storage request and egress rates for the operator host apply. A changed object, a visibility change or an exceeded budget ends the run. Repeat the command to prepare a fresh candidate once the cause is resolved.
