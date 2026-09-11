"""Explicitly limited release evidence; never export raw logs or credentials."""
import hashlib,json,shutil,tarfile
from pathlib import Path

stage=Path('/root/vidra-v064-runtime')
out=Path('/root/vidra-v064-reviewed-evidence')
out.mkdir(mode=0o700)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
save=lambda name,value:(out/name).write_text(json.dumps(value,indent=2)+'\n')
result=json.loads((stage/'result.json').read_text())
browser=result.pop('browser')
assert result['status']==browser['status']=='PASS'
for field in ('runtime_before_browser','runtime_after_browser'):
 for row in result[field]['images'].values():
  for entry in row['state'].get('Health',{}).get('Log',[]):
   entry['output_sha256']=hashlib.sha256(entry.pop('Output').encode()).hexdigest()
commands=[json.loads(line) for line in (stage/'private/commands.jsonl').read_text().splitlines()]
for row in commands:
 row['log_sha256']=sha(stage/'private'/row['log'])
 row['log_visibility']='retained privately on host; output not exported'
model_log=next(row['log'] for row in commands if row['label']=='compose-config')
model=json.loads((stage/'private'/model_log).read_text())
configuration={k:model['services']['api']['environment'].get(k) for k in (
 'VIDRA_ENV','TRANSCODING_ENABLED','TRANSCODING_PACKAGER','SEARCH_SERVICE_URL','CLAMAV_ADDR','MALWARE_SCAN_MODE',
 'RATE_LIMIT_ENABLED','RATE_LIMIT_REQUESTS','MEDIA_RATE_LIMIT_REQUESTS')}
save('result.json',result)
save('browser-result.json',browser)
save('host-commands.json',commands)
save('export-provenance.json',{'raw_result_sha256':sha(stage/'result.json'),
 'raw_browser_sha256':sha(stage/'browser-result.json'),'raw_commands_sha256':sha(stage/'private/commands.jsonl'),
 'raw_evidence_location':str(stage),'runtime_configuration':configuration,
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
