"""What one release pair implies for the REC03 drill: pure functions of two records and one migration's SQL."""
import re

ROLES = ('core', 'user', 'search')
OLD_LEDGER_PHASES = frozenset(('install', 'data', 'fp', 'backup', 'inject'))
NO_MIGRATION = 'pair carries no core migration'
NOT_LISTED = 'release record does not list the first pending migration'
NOT_INJECTABLE = 'first pending migration has no injectable statement'
REASONS = (NO_MIGRATION, NOT_LISTED, NOT_INJECTABLE)
MIGRATION = re.compile(r'([0-9]{4,})_[a-z0-9_]+\.up\.sql')
# The driver's own IDENT_RE and TYPE_RE: a value it would refuse must not be derived here.
IDENT = r'[a-z_][a-z0-9_]{0,62}'
TYPES = frozenset('UUID TEXT BOOLEAN SMALLINT INT INTEGER BIGINT REAL NUMERIC JSONB DATE TIMESTAMP TIMESTAMPTZ'.split())
# Only creations that fail when the object exists: IF NOT EXISTS and OR REPLACE do not match.
SHAPES = (('table', re.compile(rf'(?i:CREATE TABLE) ({IDENT}) ?\(')),
          # A table occupies the same PostgreSQL relation name as a view.
          ('table', re.compile(rf'(?i:CREATE VIEW) ({IDENT}) (?i:AS\b|WITH ?\()')),
          ('column', re.compile(rf'(?i:ALTER TABLE) ({IDENT}) (?i:ADD COLUMN) (?!if )({IDENT}) ([A-Za-z]+)\b')),
          ('function', re.compile(rf'(?i:CREATE FUNCTION) ({IDENT}) ?\( ?\)')))
DOLLAR_QUOTE = re.compile(r'\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$')
CONFLICTS = {'table': r'(?<!of )(?<!for )relation "{REC03_INJECT_TABLE}" already exists\b',
             'constraint': r'constraint "{REC03_INJECT_CONSTRAINT}" (?:of|for) relation "{REC03_INJECT_TABLE}" already exists\b',
             'column': r'column "{REC03_INJECT_COLUMN}" of relation "{REC03_INJECT_TABLE}" already exists\b',
             'function': r'function "{REC03_INJECT_FUNCTION}" already exists with same argument types\b'}


class Refused(ValueError):
    """str() is one of REASONS."""


def first_pending(old, new):
    """(ledger version, file name) of the first core migration the upgrade runs."""
    version = old['core_schema_version'] + 1
    if new['core_schema_version'] < version:
        raise Refused(NO_MIGRATION)
    names = [name for name in new.get('core_migrations', ())
             if MIGRATION.fullmatch(name) and int(MIGRATION.fullmatch(name)[1]) == version]
    if len(names) != 1:
        raise Refused(NOT_LISTED)
    return version, names[0]


def same_schema(old, new):
    return all(old[key] == new[key] for key in ('core_schema_version', 'search_schema_version'))


def ledger(old, new, phase):
    if phase in ('inject', 'upgrade-fail') and same_schema(old, new):
        return f"core={old['core_schema_version']}:true search={old['search_schema_version']}:false"
    if phase in OLD_LEDGER_PHASES:
        return f"core={old['core_schema_version']}:false search={old['search_schema_version']}:false"
    if phase == 'upgrade-fail':
        # deploy.sh stops at the failed core migrator, before the search one runs.
        return f"core={first_pending(old, new)[0]}:true search={old['search_schema_version']}:false"
    return f"core={new['core_schema_version']}:false search={new['search_schema_version']}:false"


def images(record):
    return tuple(f"{record['components'][role]['image']['repository']}:{record['components'][role]['tag']};"
                 for role in ROLES)


def statements(sql):
    """Top-level statements, comments removed, literal and dollar-quoted bodies blanked."""
    found, current, at = [], [], 0
    while at < len(sql):
        char, pair = sql[at], sql[at:at + 2]
        opening = DOLLAR_QUOTE.match(sql, at) if char == '$' else None
        if pair == '--':
            end = sql.find('\n', at)
            at = len(sql) if end < 0 else end
        elif pair == '/*':
            depth, at = 1, at + 2
            while at < len(sql) and depth:
                step = sql[at:at + 2]
                depth += (step == '/*') - (step == '*/')
                at += 2 if step in ('/*', '*/') else 1
            current.append(' ')
        elif char == "'":
            escapes = re.search(r'(?:^|[^A-Za-z0-9_$])[eE]$', ''.join(current)) is not None
            at += 1
            while at < len(sql) and (sql[at] != "'" or sql[at + 1:at + 2] == "'"):
                at += 2 if sql[at] == "'" or escapes and sql[at] == '\\' else 1
            at += 1
            current.append("''")
        elif char == '"':
            end = at + 1
            while end < len(sql) and (sql[end] != '"' or sql[end + 1:end + 2] == '"'):
                end += 2 if sql[end] == '"' else 1
            current.append(sql[at:end + 1])
            at = end + 1
        elif opening and not re.search(r'[A-Za-z0-9_$]$', ''.join(current)):
            close = sql.find(opening[0], opening.end())
            at = len(sql) if close < 0 else close + len(opening[0])
            current.append('$$')
        elif char == ';':
            found.append(' '.join(''.join(current).split()))
            current, at = [], at + 1
        else:
            current.append(char)
            at += 1
    found.append(' '.join(''.join(current).split()))
    return [statement for statement in found if statement]


def check_constraint(statement, earlier):
    """Select a new named CHECK from an ALTER containing only constraint drops/adds."""
    alter = re.fullmatch(rf'(?i:ALTER TABLE) ({IDENT}) (.+)', statement)
    if not alter or re.search(rf'\b{alter[1]}\b', earlier):
        return None
    # Split only on commas outside the CHECK expressions. Literal bodies have
    # already been blanked by statements(); quoted identifiers are unsupported.
    actions = alter[2]
    if '"' in actions:
        return None
    dropped, added = set(), []
    start = depth = 0
    for pos, char in enumerate(actions + ','):
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth < 0:
                return None
        elif char == ',' and depth == 0:
            clause = actions[start:pos].strip()
            drop = re.fullmatch(rf'(?i:DROP CONSTRAINT) ({IDENT})', clause)
            add = re.fullmatch(rf'(?i:ADD CONSTRAINT) ({IDENT}) (?i:CHECK) ?\(.+\)', clause)
            if drop:
                dropped.add(drop[1])
            elif add:
                added.append(add[1])
            else:
                return None
            start = pos + 1
    if depth or len(added) != len(set(added)):
        return None
    for name in added:
        if name not in dropped and not re.search(rf'\b{name}\b', earlier):
            return {'REC03_INJECT': 'constraint', 'REC03_INJECT_TABLE': alter[1], 'REC03_INJECT_CONSTRAINT': name}
    return None


def injection(sql):
    """The driver's REC03_INJECT* for the first statement that fails when its object pre-exists."""
    earlier = ''
    for statement in statements(sql):
        for kind, shape in SHAPES:
            match = shape.match(statement)
            if not match or kind == 'column' and match[3].upper() not in TYPES:
                continue
            names = match.groups()[:2 if kind == 'column' else 1]
            # An object an earlier statement touches may be dropped or created before this
            # one runs, and the migration would then not fail on it.
            if any(re.search(rf'\b{name}\b', earlier) for name in names):
                continue
            if kind == 'function':
                return {'REC03_INJECT': kind, 'REC03_INJECT_FUNCTION': names[0]}
            found = {'REC03_INJECT': kind, 'REC03_INJECT_TABLE': names[0]}
            if kind == 'column':
                found.update(REC03_INJECT_COLUMN=names[1], REC03_INJECT_TYPE=match[3].upper())
            return found
        constraint = check_constraint(statement, earlier)
        if constraint:
            return constraint
        earlier += ' ' + statement
    raise Refused(NOT_INJECTABLE)


def conflict(found):
    """What the published migrator's own error must say about the injected object."""
    return re.compile(CONFLICTS[found['REC03_INJECT']].format(**found))


def refusal(old, new):
    """restore.sh's schema refusal for a dump taken after the upgrade, under the old pins."""
    return (re.compile(rf"dump is at {new['core_schema_version']}(?![0-9])"),
            re.compile(rf"carries up to {old['core_schema_version']}(?![0-9])"),
            re.compile('Nothing was changed'))


def env(old, new, found):
    same = same_schema(old, new)
    return {'REC03_OLD': old['release'], 'REC03_NEW': new['release'], 'REC03_SAME_SCHEMA': '1' if same else '0', **found}
