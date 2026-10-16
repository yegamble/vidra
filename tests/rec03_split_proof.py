"""Private, per-upload execution proof for the published API/worker split."""
import calendar
from datetime import datetime
from decimal import Decimal
import json
import re
from uuid import UUID


class Invalid(ValueError):
    pass


def need(condition):
    if not condition:
        raise Invalid('split worker not proven')


def epoch(value):
    need(type(value) is str and re.fullmatch(r'(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,9})?', value))
    return Decimal(value)


def uuid(value):
    need(type(value) is str and str(UUID(value)) == value)
    return value


def boot(value):
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z', value)
    need(match)
    seconds = calendar.timegm(datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S').timetuple())
    return Decimal(seconds) + Decimal('0.' + (match[2] or '0'))


def snapshot_sql(video, hosts, api_id, api_boot):
    # Inputs have strict identifier/decimal syntax before interpolation. Never
    # select env, source keys, error text, metadata, or raw application logs.
    return f"""SELECT jsonb_build_object(
      'observed_epoch', extract(epoch FROM current_timestamp)::text,
      'video', (SELECT jsonb_build_object('id', id, 'created_epoch', extract(epoch FROM created_at)::text)
                FROM videos WHERE id = '{video}'),
      'processes', (SELECT coalesce(jsonb_agg(to_jsonb(p)), '[]'::jsonb) FROM (
        SELECT process_id, hostname, pid, role, version, build_commit, state,
               extract(epoch FROM started_at)::text AS started_epoch,
               extract(epoch FROM last_seen_at)::text AS last_seen_epoch
        FROM process_heartbeats WHERE hostname IN ('{hosts[0]}', '{hosts[1]}')) p),
      'jobs', (SELECT coalesce(jsonb_agg(jsonb_build_object(
        'id', t.id, 'video_id', t.video_id, 'state', t.state, 'transcode_type', t.transcode_type,
        'created_epoch', extract(epoch FROM t.created_at)::text,
        'runs', (SELECT coalesce(jsonb_agg(jsonb_build_object(
          'id', j.id, 'type', j.type, 'queue', j.queue, 'source_id', j.source_id,
          'resource_type', j.resource_type, 'resource_id', j.resource_id, 'state', j.state, 'worker_id', j.worker_id,
          'created_epoch', extract(epoch FROM j.created_at)::text,
          'claimed_epoch', extract(epoch FROM j.claimed_at)::text,
          'started_epoch', extract(epoch FROM j.started_at)::text,
          'finished_epoch', extract(epoch FROM j.finished_at)::text,
          'events', (SELECT coalesce(jsonb_agg(jsonb_build_object(
            'cursor', e.cursor, 'kind', e.kind, 'state', e.state, 'worker_id', e.worker_id,
            'occurred_epoch', extract(epoch FROM e.occurred_at)::text)), '[]'::jsonb)
            FROM job_events e WHERE e.job_id = j.id))), '[]'::jsonb)
          FROM job_runs j WHERE j.queue = 'transcode_jobs' AND j.source_id = t.id::text))), '[]'::jsonb)
        FROM transcode_jobs t WHERE t.video_id = '{video}'),
      'hls_succeeded', (SELECT count(*) FROM transcode_steps WHERE video_id = '{video}'
                        AND format = 'hls' AND state = 'succeeded'),
      'api_runs', (SELECT count(*) FROM job_runs WHERE worker_id = '{api_id}'
        AND (claimed_at >= to_timestamp({api_boot}) OR started_at >= to_timestamp({api_boot})
             OR updated_at >= to_timestamp({api_boot}) OR created_at >= to_timestamp({api_boot}))),
      'api_events', (SELECT count(*) FROM job_events WHERE worker_id = '{api_id}'
                     AND occurred_at >= to_timestamp({api_boot})));"""


def verify(facts, containers, core_record, query):
    """Return only success or a fixed failure; query rows and identities stay private.

    Caller already proves these current containers' immutable image identities.
    Missing best-effort bookkeeping cannot substitute for execution evidence.
    """
    try:
        _verify(facts, containers, core_record, query)
    except Exception:
        raise Invalid('split worker not proven') from None


def _verify(facts, containers, core_record, query):
    video, before = uuid(facts['video2_id']), epoch(facts['split_before'])
    cursor = facts['split_cursor']
    need(type(cursor) is str and re.fullmatch(r'(?:0|[1-9][0-9]{0,18})', cursor))
    cursor = int(cursor)
    commit = core_record['commit']
    need(type(commit) is str and re.fullmatch('[0-9a-f]{40}', commit))
    identities, boots, hosts = {}, {}, []
    for role in ('api', 'worker'):
        container = containers[role]
        config = container['Config']
        env = config['Env']
        need(type(env) is list and all(type(item) is str for item in env))
        need([item for item in env if item.startswith('VIDRA_ROLE=')] == ['VIDRA_ROLE=' + role])
        need(container['Path'] == '/app/api' and container['Args'] == [])
        host_config = container['HostConfig']
        need(host_config.get('Init') is None or host_config['Init'] is False)
        need(host_config['PidMode'] == '')
        hostname = config['Hostname']
        need(type(hostname) is str and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}', hostname))
        hosts.append(hostname)
        identities[role] = hostname + ':1'
        boots[role] = boot(container['State']['StartedAt'])
    need(len(set(hosts)) == 2)
    data = json.loads(query(snapshot_sql(video, hosts, identities['api'], boots['api'])))
    observed = epoch(data['observed_epoch'])
    need(before <= observed)
    processes = data['processes']
    need(type(processes) is list and len(processes) == 2)
    starts = {}
    for role, hostname in zip(('api', 'worker'), hosts):
        process, = [p for p in processes if p['process_id'] == identities[role]]
        need(process['hostname'] == hostname and type(process['pid']) is int and process['pid'] == 1)
        need(process['role'] == role and process['state'] == 'running' and process['version'] == core_record['tag'])
        revision = process['build_commit']
        need(type(revision) is str and re.fullmatch('[0-9a-f]{7,40}', revision) and commit.startswith(revision))
        starts[role] = epoch(process['started_epoch'])
        seen = epoch(process['last_seen_epoch'])
        need(boots[role] <= starts[role] <= seen <= observed and seen >= observed - 30)
    created = epoch(data['video']['created_epoch'])
    need(data['video']['id'] == video and before <= created <= observed)
    need(all(type(data[key]) is int and data[key] == 0 for key in ('api_runs', 'api_events')))
    need(type(data['hls_succeeded']) is int and data['hls_succeeded'] > 0)
    jobs = data['jobs']
    need(type(jobs) is list and jobs)
    job_ids, run_ids, cursors, hls = set(), set(), set(), False
    for job in jobs:
        job_id = uuid(job['id'])
        need(job_id not in job_ids and job['video_id'] == video and job['state'] == 'done')
        job_ids.add(job_id)
        need(job['transcode_type'] in ('all', 'hls', 'web_video'))
        hls |= job['transcode_type'] in ('all', 'hls')
        job_created = epoch(job['created_epoch'])
        need(type(job['runs']) is list)
        run, = job['runs']
        run_id = uuid(run['id'])
        need(run_id not in run_ids)
        run_ids.add(run_id)
        need(run['type'] == 'video_transcode' and run['queue'] == 'transcode_jobs' and run['source_id'] == job_id)
        need(run['resource_type'] == 'video' and run['resource_id'] == video and run['state'] == 'succeeded')
        need(run['worker_id'] == identities['worker'])
        run_created, started, claimed, finished = (epoch(run[key]) for key in
                                                  ('created_epoch', 'started_epoch', 'claimed_epoch', 'finished_epoch'))
        need(created <= job_created <= run_created <= started <= claimed <= finished <= observed)
        need(started >= starts['worker'])
        need(type(run['events']) is list)
        execution = {'started': [], 'succeeded': []}
        for event in run['events']:
            position, occurred = event['cursor'], epoch(event['occurred_epoch'])
            need(type(position) is int and position > cursor and position not in cursors)
            cursors.add(position)
            need(job_created <= occurred <= observed and event['worker_id'] == identities['worker'])
            if event['kind'] in execution:
                need(event['state'] == ('running' if event['kind'] == 'started' else 'succeeded'))
                execution[event['kind']].append((position, occurred))
        need(execution['started'] and execution['succeeded'])
        need(min(execution['started']) < max(execution['succeeded']))
        need(all(started <= time <= finished for events in execution.values() for _, time in events))
    need(hls)
