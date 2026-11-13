"""Three real release pairs for the REC03 tests, with every expectation typed here by hand.

Nothing below is computed from the records or the SQL: these are the values the code under test
must derive. tests/rec03_migrations/ holds each pair's first pending migration, byte for byte from
vidra-core at the newer record's core commit.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _case(**fields):
    return SimpleNamespace(**fields)


CASES = (
    _case(name='v0.7.7 -> v0.7.8: mixed tags, a column', old='v0.7.7', new='v0.7.8', explicit_previous='',
          first=(152, '0152_remote_video_sensitive.up.sql'),
          sha256='86884c3ec3e9bc7312045b524cfd3fb2f99ef650bbfcf93a61c7a76a9117923e',
          ledger_old='core=151:false search=18:false', ledger_failed='core=152:true search=18:false',
          ledger_new='core=182:false search=18:false',
          images_old='ghcr.io/yegamble/vidra-core:v0.7.7;ghcr.io/yegamble/vidra-user:v0.7.7;ghcr.io/yegamble/vidra-search:v0.7.3;',
          images_new='ghcr.io/yegamble/vidra-core:v0.7.8;ghcr.io/yegamble/vidra-user:v0.7.8;ghcr.io/yegamble/vidra-search:v0.7.8;',
          injection={'REC03_INJECT': 'column', 'REC03_INJECT_TABLE': 'remote_videos',
                     'REC03_INJECT_COLUMN': 'is_sensitive', 'REC03_INJECT_TYPE': 'BOOLEAN'},
          ddl='ALTER TABLE remote_videos ADD COLUMN is_sensitive BOOLEAN',
          undo='ALTER TABLE remote_videos DROP COLUMN is_sensitive',
          error='column "is_sensitive" of relation "remote_videos" already exists',
          pre_core='151', pre_search='18', post_core='182', post_search='18',
          refusal='the dump is at 182; pinned VIDRA_CORE_TAG=v0.7.7 carries up to 151. Nothing was changed.'),
    _case(name='v0.7.19 -> v0.7.20: one migration, a table', old='v0.7.19', new='v0.7.20', explicit_previous='',
          first=(189, '0189_user_consents.up.sql'),
          sha256='f2acef2ae0067b348e9fc793ee944b0f3fee6cd0303671c6e8f27c8e1cf685e4',
          ledger_old='core=188:false search=21:false', ledger_failed='core=189:true search=21:false',
          ledger_new='core=189:false search=21:false',
          images_old='ghcr.io/yegamble/vidra-core:v0.7.19;ghcr.io/yegamble/vidra-user:v0.7.19;ghcr.io/yegamble/vidra-search:v0.7.19;',
          images_new='ghcr.io/yegamble/vidra-core:v0.7.20;ghcr.io/yegamble/vidra-user:v0.7.20;ghcr.io/yegamble/vidra-search:v0.7.20;',
          injection={'REC03_INJECT': 'table', 'REC03_INJECT_TABLE': 'user_consents'},
          ddl='CREATE TABLE user_consents (rec03_injected BOOLEAN)',
          undo='DROP TABLE user_consents',
          error='relation "user_consents" already exists',
          pre_core='188', pre_search='21', post_core='189', post_search='21',
          refusal='the dump is at 189; pinned VIDRA_CORE_TAG=v0.7.19 carries up to 188. Nothing was changed.'),
    _case(name='v0.7.8 -> v0.7.20: twelve releases, a function, search moves', old='v0.7.8', new='v0.7.20',
          explicit_previous='v0.7.8',
          first=(183, '0183_remote_actors_own_host_inboxes.up.sql'),
          sha256='e11559c5bb5fc8d129f76ceb6718277969acbb214ae7b46c9a27485747e707eb',
          ledger_old='core=182:false search=18:false', ledger_failed='core=183:true search=18:false',
          ledger_new='core=189:false search=21:false',
          images_old='ghcr.io/yegamble/vidra-core:v0.7.8;ghcr.io/yegamble/vidra-user:v0.7.8;ghcr.io/yegamble/vidra-search:v0.7.8;',
          images_new='ghcr.io/yegamble/vidra-core:v0.7.20;ghcr.io/yegamble/vidra-user:v0.7.20;ghcr.io/yegamble/vidra-search:v0.7.20;',
          injection={'REC03_INJECT': 'function', 'REC03_INJECT_FUNCTION': 'clear_cross_host_remote_inboxes'},
          ddl="CREATE FUNCTION clear_cross_host_remote_inboxes() RETURNS BOOLEAN LANGUAGE sql AS 'SELECT true'",
          undo='DROP FUNCTION clear_cross_host_remote_inboxes()',
          error='function "clear_cross_host_remote_inboxes" already exists with same argument types',
          pre_core='182', pre_search='18', post_core='189', post_search='21',
          refusal='the dump is at 189; pinned VIDRA_CORE_TAG=v0.7.8 carries up to 182. Nothing was changed.'),
)


def records(case):
    return tuple(json.loads((ROOT / 'releases' / f'{tag}.json').read_text()) for tag in (case.old, case.new))


def sql(case):
    data = (ROOT / 'tests/rec03_migrations' / case.first[1]).read_bytes()
    if hashlib.sha256(data).hexdigest() != case.sha256:
        raise AssertionError(f'{case.first[1]} is no longer the file vidra-core shipped')
    return data.decode()


def others(case):
    return [other for other in CASES if other is not case]
