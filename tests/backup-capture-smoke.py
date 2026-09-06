#!/usr/bin/env python3
"""Capture a matched local-media recovery set on the disposable A36 fixture."""
import json,pathlib,subprocess,time,hashlib,re,sys
fixture,out=map(pathlib.Path,sys.argv[1:]);prepared=json.loads((fixture/'result.json').read_text())
assert prepared['status']=='PASS'
vm,project=prepared['vm'],prepared['project'];root=prepared['guest_root']+'/installation'
assert re.fullmatch(r'vidra-a02-\d+-\d+',vm) and re.fullmatch(r'vidra-a03-\d+-\d+',project)
assert re.fullmatch(r'/home/ubuntu/vidra-a08-\d+/installation',root)
out.mkdir(mode=0o700)
guest_dir='/home/ubuntu/vidra-a36-set-'+str(int(time.time()))
def guest(*a):return subprocess.check_output(['multipass','exec',vm,'--','sudo',*a],stderr=subprocess.STDOUT,timeout=180)
services=[project+'-'+s+'-1' for s in ['api','search','frontend']]
result={'helper_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'fixture':prepared,'status':'UNVERIFIED','vm':vm,'project':project,'guest_dir':guest_dir,'files':{}}
try:
 guest('docker','stop',*services)
 inspect=json.loads(guest('docker','inspect',project+'-api-1'))[0]
 assert inspect['Image']==prepared['images']['vidra-core:a08-source']
 frontend=json.loads(guest('docker','inspect',project+'-frontend-1'))[0]
 assert frontend['Image']==prepared['images']['vidra-user:a08-source']
 script_hash=guest('sha256sum',root+'/deploy/backup.sh').decode().split()[0]
 assert script_hash==hashlib.sha256(pathlib.Path('deploy/backup.sh').read_bytes()).hexdigest()
 result['backup_sha256']=script_hash
 media_mount=next(m for m in inspect['Mounts'] if m['Destination']=='/app/data')
 assert media_mount['Type']=='volume' and media_mount['Name']==project+'_media_data'
 result['quiesced_at']=time.time()
 log=guest('env','COMPOSE_PROJECT_NAME='+project,'BACKUP_DIR='+guest_dir,'bash',root+'/deploy/backup.sh');(out/'private-backup.log').write_bytes(log)
 media=media_mount['Source']
 detail=json.loads(guest('python3','-c',"import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); print(json.dumps({'dump':[f.name for f in p.glob('*.dump.gz')][0],'config':[f.name for f in p.glob('*.tar.gz')][0]}))",guest_dir))
 stamp=detail['dump'].removeprefix('vidra-').removesuffix('.dump.gz');detail['media']='media_data-'+stamp+'.tar.gz'
 guest('tar','-czf',guest_dir+'/'+detail['media'],'-C',media,'.')
 guest('chmod','600',guest_dir+'/'+detail['media'])
 for kind,name in detail.items():
  transfer='/home/ubuntu/vidra-a36-transfer-'+name
  guest('install','-o','ubuntu','-g','ubuntu','-m','600',guest_dir+'/'+name,transfer)
  subprocess.run(['multipass','transfer',vm+':'+transfer,str(out/name)],check=True,capture_output=True,timeout=180)
  (out/name).chmod(0o600);guest('rm',transfer)
  b=(out/name).read_bytes();result['files'][kind]={'name':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
 result['snapshot_completed_at']=time.time();result['status']='PASS'
finally:
 guest('docker','start',*services)
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'status':result['status'],'output':str(out)}))
