# Private synthetic importer fixture

This preparatory tool generates playable media for an **importer schema subset**
grounded in `vidra-core@04a7f0e127177b631eb323d04d330673fee044f9` (v0.7.8).
It does not run a PeerTube server, generate a real PeerTube export, certify a
PeerTube version, provision hosts/storage, or qualify G10. Representative source
migration, recovery, and browser playback remain unverified.

The media-only first slice requires Python 3.11+ and `ffmpeg`/`ffprobe` on PATH,
including the `libx264` and AAC encoders. It installs nothing and uses no network:

```sh
python3 tests/peertube_fixture_media.py --out /absolute/private-parent/NEW-fixture
```

Use a canonical absolute path outside Git repositories. Existing paths, symlinks,
and missing parents are refused. The new directory is 0700; generated files are
0600. Failure leaves private partial output and `tools.log` for local inspection;
use a new output path for another attempt. Never commit generated state or logs.

`source-media/` models a synthetic local source media root: seven identical-content
4-second 320×180 H.264/AAC originals, muxed fMP4 HLS, HLS-only playback, separate
audio/video fMP4 HLS, WebVTT, JPEG thumbnail/poster and a 2×2 storyboard sprite.
The `avatars/` PNG requires a future isolated source HTTP service. Thumbnails,
storyboards and avatars model source-host files; they are not PeerTube S3 object
keys. Only web videos, HLS and captions belong in source object storage. No HTTP
service is started.

`inventory.json` records each object's SHA-256/size, exact executable hashes and
version output, commands, probes, HLS dependencies, and case-to-key mappings.
The generator resolves local playlist dependencies and decodes originals,
masters and images with ffmpeg before declaring success. It asserts neither
byte identity across tool versions nor successful Vidra playback/import.

The ten named cases reserve public, unlisted, private, internal,
password-protected, draft, HLS-only, split-audio, blacklisted and missing-media
relationships. Missing-media deliberately has neither file nor
playlist rows; it does not simulate a missing object referenced by a file row.
Schema marker 1040 is supported; 1041 is reserved for refusal testing. Neither
marker represents a running PeerTube server or upstream schema certification.

## Private SQL and credentials

After generating media, create a separate new private output directory:

```sh
python3 tests/peertube_fixture_database.py \
  --media /absolute/private-parent/NEW-fixture \
  --out /absolute/private-parent/NEW-database
```

The tool verifies the media inventory hashes, private modes and frozen contract.
It requires OpenSSL and real bcrypt: the Python `bcrypt` package, or Python
3.11–3.12 with libcrypt's Blowfish method. No dependencies are installed.
Fresh random passwords use bcrypt cost 12; four actor RSA keys use 2048 bits.
Passwords, hashes, private keys, SQL and inventory remain in 0700/0600 output.
The CLI prints fixed result/error labels. Treat **all** generated state as private.

`source-1040.sql` creates and seeds only the frozen importer's query subset;
`source-1041.sql` changes its marker for a future default-preflight refusal test.
The supported importer contract is 700–1040. These are plaintext SQL inputs for
new disposable source databases, not real PeerTube exports or Vidra restore
archives. The generator creates/loads no database and runs no migration/import.
It omits upstream constraints, indexes, sequences, grants and server behavior.

The graph includes an active and a blocked user, two channels, all ten video
cases, threaded/deleted comments, regular/Watch Later playlists, accepted/pending
local follows, a public blacklisted video, tags, chapters, ratings, captions,
thumbnail selection and storyboard geometry. HLS file rows are explicitly
synthetic **playlist descriptors**: measured sizes are playlist bytes, not encoded
track totals or upstream whole-MP4 semantics. This does not verify rendition-size
accounting. Avatar rows remain empty because avatar import always requires a live
HTTP source; the generated PNG is reserved for a future scoped harness.

The default actor origin is `https://synthetic-peertube.invalid`.
`--source-origin http://isolated-source-host:port` may record a future fixture
origin; it starts no listener or network request. For an S3-source rehearsal,
host artwork must separately be served under the frozen importer's `/lazy-static/`
routes. No remote followers, plugin auth, history or per-user ZIP are generated.
Neither source SQL has been imported through the released CLI as qualification;
G10 and representative-source/browser evidence remain **UNVERIFIED**.
