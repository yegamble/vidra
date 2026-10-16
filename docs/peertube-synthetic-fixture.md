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
relationships for a separate private SQL generator. This slice contains no
database or credentials. Missing-media deliberately has neither file nor
playlist rows; it does not simulate a missing object referenced by a file row.
Schema marker 1040 is supported; 1041 is reserved for refusal testing. Neither
marker represents a running PeerTube server or upstream schema certification.
