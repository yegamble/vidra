#!/usr/bin/env python3
"""Private synthetic media for the v0.7.8 importer schema subset, not G10 proof."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


CORE_COMMIT = '04a7f0e127177b631eb323d04d330673fee044f9'
CASES = ('public', 'unlisted', 'private', 'internal', 'password', 'draft',
         'hls_only', 'split_audio', 'blacklisted', 'missing_media')
UUIDS = {name: f'00000000-0000-4000-8000-{number:012d}'
         for number, name in enumerate(CASES, 1)}


class FixtureError(Exception):
    """Only fixed error categories may cross the command-line boundary."""


def new_private_directory(path):
    path = Path(path)
    try:
        canonical = path.resolve()
    except (OSError, RuntimeError):
        raise FixtureError('output_path_refused') from None
    if not path.is_absolute() or path != canonical or not path.parent.is_dir():
        raise FixtureError('output_path_refused')
    if any((parent / '.git').is_file() or (parent / '.git/HEAD').exists()
           for parent in (path, *path.parents)):
        raise FixtureError('repository_output_refused')
    try:
        path.mkdir(mode=0o700)  # Exclusive creation also refuses dangling symlinks.
    except FileExistsError:
        raise FixtureError('output_exists') from None
    return path


def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
        handle.write(data.encode() if isinstance(data, str) else data)
    path.chmod(0o600)


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def hls_dependencies(path):
    """Resolve the deliberately flat, local-only fixture playlists before probing."""
    found = []
    text = Path(path).read_text()
    if not text.startswith('#EXTM3U\n'):
        raise FixtureError('playlist_invalid')
    durations = re.findall(r'^#EXTINF:([^,]+),', text, re.M)
    if durations and ('#EXT-X-ENDLIST' not in text or not all(
            math.isfinite(float(value)) and float(value) > 0 for value in durations)):
        raise FixtureError('playlist_invalid')
    for line in text.splitlines():
        refs = re.findall(r'URI="([^"]+)"', line) if line.startswith('#') else [line]
        for ref in filter(None, refs):
            if not re.fullmatch(r'[A-Za-z0-9_-]+\.(m3u8|m4s|mp4)', ref):
                raise FixtureError('playlist_dependency_refused')
            dependency = Path(path).parent / ref
            if dependency.is_symlink() or not dependency.is_file() or not dependency.stat().st_size:
                raise FixtureError('playlist_dependency_missing')
            found.append(ref)
    if not found:
        raise FixtureError('playlist_invalid')
    return found


class Tools:
    def __init__(self, root):
        self.root, self.commands, self.identities = root, [], {}
        self.paths = {}
        for name in ('ffmpeg', 'ffprobe'):
            executable = shutil.which(name)
            if not executable:
                raise FixtureError('media_tool_missing')
            self.paths[name] = str(Path(executable).resolve())

    def run(self, name, args):
        command = [self.paths[name], *map(str, args)]
        self.commands.append(command)
        # Raw tool output stays private, including failures. No shell is involved.
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=120, check=False)
        with (self.root / 'tools.log').open('ab') as log:
            log.write((json.dumps(command) + '\n').encode())
            log.write(completed.stdout + completed.stderr)
        if completed.returncode:
            raise FixtureError('media_tool_failed')
        return completed.stdout

    def identify(self):
        for name, path in self.paths.items():
            self.identities[name] = dict(path=path, sha256=sha256(path),
                                        version=self.run(name, ['-version']).decode())

    def encode(self, args):
        return self.run('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                                   '-threads', '1', '-filter_threads', '1', *args])

    def probe(self, path, expected=(('video', 'h264'), ('audio', 'aac'))):
        result = json.loads(self.run('ffprobe', ['-v', 'error', '-show_streams',
                                                 '-show_format', '-of', 'json', path]))
        codecs = {(stream['codec_type'], stream['codec_name']) for stream in result.get('streams', [])}
        if codecs != set(expected) or not (
                3.8 <= float(result['format'].get('duration', 0)) <= 4.2):
            raise FixtureError('media_probe_invalid')
        return {key: result[key] for key in ('streams', 'format')}

    def decode(self, path):
        self.encode(['-xerror', '-err_detect', 'explode', '-i', path, '-map', '0', '-f', 'null', '-'])


def hls(tools, original, directory, split=False):
    directory.mkdir(mode=0o700, parents=True)
    common = ['-hls_time', '2', '-hls_playlist_type', 'vod', '-hls_segment_type', 'fmp4',
              '-hls_flags', 'independent_segments']
    tracks = ('video', 'audio') if split else ('video',)
    for track in tracks:
        mapping = ['-map', '0:v:0', '-an'] if split and track == 'video' else (
            ['-map', '0:a:0', '-vn'] if split else ['-map', '0:v:0', '-map', '0:a:0'])
        tools.encode(['-i', original, *mapping, '-c', 'copy', *common,
                      '-hls_fmp4_init_filename', track + '-init.mp4',
                      '-hls_segment_filename', directory / (track + '-%03d.m4s'),
                      directory / (track + '.m3u8')])
    master = '#EXTM3U\n#EXT-X-VERSION:7\n'
    if split:
        master += ('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Synthetic",'
                   'DEFAULT=YES,AUTOSELECT=YES,URI="audio.m3u8"\n')
    master += '#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=320x180'
    master += ',AUDIO="audio"\n' if split else '\n'
    write_private(directory / 'master.m3u8', master + 'video.m3u8\n')


def generate(output):
    # Resolve prerequisites before creating output; no installation or network calls.
    if not all(shutil.which(name) for name in ('ffmpeg', 'ffprobe')):
        raise FixtureError('media_tool_missing')
    previous_umask = os.umask(0o077)
    try:
        root = new_private_directory(output)
        write_private(root / 'tools.log', b'')
        tools = Tools(root)
        tools.identify()
        media_root = root / 'source-media'
        base = media_root / 'web-videos' / (UUIDS['public'] + '.mp4')
        base.parent.mkdir(mode=0o700, parents=True)
        tools.encode(['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=25',
                      '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                      '-map', '0:v:0', '-map', '1:a:0', '-t', '4', '-c:v', 'libx264',
                      '-threads:v', '1', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-g', '50', '-keyint_min', '50',
                      '-sc_threshold', '0', '-flags', '+cgop', '-c:a', 'aac', '-profile:a', 'aac_low',
                      '-ar', '48000', '-ac', '2', '-b:a', '64k', '-movflags', '+faststart', base])
        videos = {}
        for name in CASES:
            entry = videos[name] = dict(uuid=UUIDS[name], original=None, hls=None)
            if name not in ('hls_only', 'split_audio', 'missing_media'):
                original = base.parent / (UUIDS[name] + '.mp4')
                if original != base:
                    write_private(original, base.read_bytes())
                entry['original'] = original.relative_to(media_root).as_posix()
            if name in ('public', 'hls_only', 'split_audio'):
                directory = media_root / 'streaming-playlists/hls' / UUIDS[name]
                hls(tools, base, directory, split=name == 'split_audio')
                entry['hls'] = (directory / 'master.m3u8').relative_to(media_root).as_posix()
        images = [('source-media/thumbnails/thumbnail.jpg', 'scale=160:90', 160, 90),
                  ('source-media/thumbnails/poster.jpg', 'scale=320:180', 320, 180),
                  ('source-media/storyboards/sprite.jpg', 'fps=1,scale=160:90,tile=2x2', 320, 180),
                  ('source-media/avatars/avatar.png', 'scale=128:128', 128, 128)]
        probes = {}
        for relative, filter_value, width, height in images:
            path = root / relative
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            tools.encode(['-i', base, '-vf', filter_value, '-frames:v', '1', path])
            # Still images have no meaningful duration; inspect dimensions and decode.
            data = json.loads(tools.run('ffprobe', ['-v', 'error', '-show_streams', '-of', 'json', path]))
            if [(stream['width'], stream['height']) for stream in data['streams']] != [(width, height)]:
                raise FixtureError('image_dimensions_invalid')
            probes[relative] = data
            tools.decode(path)
        write_private(media_root / 'captions/fixture-en.vtt',
                      'WEBVTT\n\n00:00.000 --> 00:04.000\nSynthetic importer fixture.\n')
        dependencies = {}
        for path in sorted(media_root.rglob('*.m3u8')):
            dependencies[path.relative_to(root).as_posix()] = hls_dependencies(path)
        split = media_root / 'streaming-playlists/hls' / UUIDS['split_audio']
        for track, kind, codec in (('video', 'video', 'h264'), ('audio', 'audio', 'aac')):
            path = split / (track + '.m3u8')
            probes[path.relative_to(root).as_posix()] = tools.probe(path, [(kind, codec)])
        for relative in [videos['public']['original'],
                         *(videos[name]['hls'] for name in ('public', 'hls_only', 'split_audio'))]:
            path = media_root / relative
            probes[path.relative_to(root).as_posix()] = tools.probe(path)
            tools.decode(path)
        files = {}
        for path in sorted(media_root.rglob('*')):
            if path.is_file():
                if not path.stat().st_size:
                    raise FixtureError('empty_media_file')
                path.chmod(0o600)
                files[path.relative_to(root).as_posix()] = dict(size=path.stat().st_size,
                                                              sha256=sha256(path))
        inventory = dict(format='vidra-peertube-importer-subset-media-v1', core_commit=CORE_COMMIT,
                         qualification='UNVERIFIED', source_server='none; synthetic importer schema subset',
                         intended_schema_marker=1040, unsupported_schema_marker=1041,
                         byte_reproducibility='not asserted across tool versions',
                         videos=videos, files=files, probes=probes, hls_dependencies=dependencies,
                         storage_families=dict(object_store=['web-videos', 'streaming-playlists/hls', 'captions'],
                                               source_host_only=['thumbnails', 'storyboards', 'avatars']),
                         tools=tools.identities, commands=tools.commands,
                         exclusions=['No database or credentials in this media-only slice.',
                                     'Artwork models source-host files, not PeerTube object-store keys.',
                                     'avatars requires a future isolated source HTTP service.',
                                     'missing_media intentionally has no file or playlist rows.'])
        write_private(root / 'inventory.json', json.dumps(inventory, indent=2) + '\n')
        return inventory
    finally:
        os.umask(previous_umask)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='new canonical absolute directory outside Git repositories')
    arguments = parser.parse_args(argv)
    try:
        generate(arguments.out)
    except FixtureError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        print('fixture_generation_failed', file=sys.stderr)
        return 1
    print('peertube_media_fixture_created')
    return 0


if __name__ == '__main__':
    sys.exit(main())
