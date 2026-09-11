"""Explicitly limited release evidence; never export raw logs or credentials."""
import hashlib,json,shutil,sys,tarfile
from pathlib import Path

stage=Path('/root/vidra-v064-runtime')
out=Path('/root/vidra-v064-reviewed-evidence')
out.mkdir(mode=0o700)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
save=lambda name,value:(out/name).write_text(json.dumps(value,indent=2)+'\n')
result=json.loads((stage/'result.json').read_text())
browser=result.pop('browser')
assert browser['status']=='PASS'
completion=None
completion_stage=Path(sys.argv[1]) if len(sys.argv)==2 else None
if result['status']!='PASS':
 assert completion_stage is not None
 completion=json.loads((completion_stage/'completion.json').read_text())
 assert result['status']=='FAIL' and result['error']=='B2 does not attest the uploaded original bytes'
 assert completion['status']=='PASS' and completion['original_result_sha256']==sha(stage/'result.json')
 assert completion['original_browser_sha256']==sha(stage/'browser-result.json')
snapshots=[result[field] for field in ('runtime_before_browser','runtime_after_browser') if field in result]
if completion:snapshots.append(completion['runtime_after_browser'])
for snapshot in snapshots:
 for row in snapshot['images'].values():
  for entry in row['state'].get('Health',{}).get('Log',[]):
   entry['output_sha256']=hashlib.sha256(entry.pop('Output').encode()).hexdigest()
commands=[]
for location in ([stage,completion_stage] if completion else [stage]):
 for line in (location/'private/commands.jsonl').read_text().splitlines():
  row=json.loads(line)
  row['evidence_directory']=str(location)
  row['log_sha256']=sha(location/'private'/row['log'])
  row['log_visibility']='retained privately on host; output not exported'
  commands.append(row)
model_log=next(row['log'] for row in commands if row['label']=='compose-config')
model=json.loads((stage/'private'/model_log).read_text())
configuration={k:model['services']['api']['environment'].get(k) for k in (
 'VIDRA_ENV','TRANSCODING_ENABLED','TRANSCODING_PACKAGER','SEARCH_SERVICE_URL','CLAMAV_ADDR','MALWARE_SCAN_MODE',
 'RATE_LIMIT_ENABLED','RATE_LIMIT_REQUESTS','MEDIA_RATE_LIMIT_REQUESTS','STORAGE_BACKEND',
 'STORAGE_S3_ENDPOINT','STORAGE_S3_REGION','STORAGE_S3_BUCKET','STORAGE_S3_USE_SSL','STORAGE_S3_FORCE_PATH_STYLE')}
# A rendered model alone does not prove the live API/worker use that store.
# Inspect logs were captured on both sides of the browser run; export only
# storage identity, checking the actual credential privately against the key
# whose single-bucket provider authorization the runner already validated.
runtime_storage=[]
if result.get('storage',{}).get('provider')=='Backblaze B2':
 spec=result['storage']
 key=json.loads(Path('/root/vidra-v064-b2-key.json').read_text())
 expected={'STORAGE_BACKEND':'s3','STORAGE_S3_ENDPOINT':spec['endpoint'],
  'STORAGE_S3_REGION':spec['region'],'STORAGE_S3_BUCKET':spec['bucket'],
  'STORAGE_S3_USE_SSL':'true','STORAGE_S3_FORCE_PATH_STYLE':'false'}
 for entry in commands:
  if entry['label']!='inspect-container':continue
  container=json.loads((Path(entry['evidence_directory'])/'private'/entry['log']).read_text())[0]
  service=container['Config']['Labels']['com.docker.compose.service']
  if service not in ('api','worker'):continue
  env=dict(value.split('=',1) for value in container['Config']['Env'] if '=' in value)
  assert all(env.get(name)==value for name,value in expected.items()),'live storage identity differs'
  assert env['STORAGE_S3_ACCESS_KEY']==key['access_key'],'live storage access key differs'
  assert env['STORAGE_S3_SECRET_KEY']==key['secret_key'],'live storage secret differs'
  runtime_storage.append({'service':service,'container_id':container['Id'],
   'observed_at':entry['started_at'],'configuration':expected,
   'credential_matches_verified_single_bucket_key':True})
 assert sum(row['service']=='api' for row in runtime_storage)>=2
 if 'worker' in model['services']:
  assert sum(row['service']=='worker' for row in runtime_storage)>=2
save('result.json',result)
save('browser-result.json',browser)
save('host-commands.json',commands)
if completion:save('completion.json',completion)
save('export-provenance.json',{'raw_result_sha256':sha(stage/'result.json'),
 'raw_browser_sha256':sha(stage/'browser-result.json'),'raw_commands_sha256':sha(stage/'private/commands.jsonl'),
 'raw_evidence_location':str(stage),'runtime_configuration':configuration,
 'actual_runtime_storage':runtime_storage,
 'completion_raw_sha256':sha(completion_stage/'completion.json') if completion else None,
 'original_failure_preserved':bool(completion),
 'scope':'Sanitized result/browser measurements, command arguments and raw-log hashes, four requested browser screenshots. No raw logs, generated environment, credentials, database or application storage exported.'})
for name,expected in browser['screenshots'].items():
 assert name in ('owner-claimed.png','upload-published.png','playback-advancing.png','search-result.png')
 assert sha(stage/name)==expected
 shutil.copyfile(stage/name,out/name)
# Check all exported text against actual generated secrets while those values
# remain on the host. Do not print either values or a matching excerpt.
secrets=[json.loads((stage/'private/owner.json').read_text())['password']]
for line in Path('/opt/vidra/env/production.env').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  key,value=line.split('=',1)
  if any(word in key for word in ('SECRET','PASSWORD','TOKEN','KEK','KEY')) and len(value)>=12:
   secrets.append(value.strip('"\''))
for path in out.glob('*.json'):
 content=path.read_text()
 assert not any(secret and secret in content for secret in secrets),'secret detected; export refused'
save('export-hashes.json',{p.name:sha(p) for p in sorted(out.iterdir())})
archive=Path('/root/vidra-v064-reviewed-evidence.tar.gz')
with tarfile.open(archive,'w:gz') as tar:
 for path in sorted(out.iterdir()):tar.add(path,arcname=path.name)
print(json.dumps({'files':[p.name for p in sorted(out.iterdir())],'archive_sha256':sha(archive),'secret_scan':'PASS'}))
