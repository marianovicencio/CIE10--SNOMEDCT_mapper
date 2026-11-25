from pathlib import Path
import datetime,json,subprocess,time,urllib.request,urllib.error,re
base='http://127.0.0.1:8081'
root=Path.cwd()
out=root/'data/runtime'
out.mkdir(parents=True,exist_ok=True)
status_file=out/'snomed-import.json'
if status_file.exists():raise SystemExit('Ya hay registro de este intento; revisar antes de repetir.')
state={'state':'running','base_url':base,'compose_project':'cie10-snomed','imports':{}}
def save(stage,**extra):
    state.update(stage=stage,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra)
    tmp=status_file.with_suffix('.tmp')
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(status_file)
    print(stage,extra,flush=True)
def request(path,payload=None):
    req=urllib.request.Request(base+path,data=None if payload is None else json.dumps(payload).encode(),
        headers={'Accept':'application/json','Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            body=r.read()
            return (json.loads(body) if body else None),r.headers.get('Location')
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{path}: HTTP {e.code} {e.read(2000).decode(errors="replace")}') from e
def rf2(label,path,branch,short_name,expected):
    _,location=request('/imports',{'branchPath':branch,'type':'SNAPSHOT','createCodeSystemVersion':True})
    job=(location or '').split('/')[-1]
    if not re.fullmatch(r'[0-9a-f-]{36}',job):raise RuntimeError('Identificador de importación inesperado')
    state['imports'][label]={'job':job,'branch':branch,'archive':path.name}
    save('upload_'+label)
    subprocess.run(['curl','-sS','--fail-with-body','--connect-timeout','10','--max-time','1200','-F','file=@'+str(path),base+'/imports/'+job+'/archive'],check=True)
    started=time.monotonic()
    while True:
        info,_=request('/imports/'+job)
        status=info.get('status')
        state['imports'][label]['status']=status
        save('import_'+label,job_status=status,elapsed_seconds=round(time.monotonic()-started))
        if status=='FAILED':raise RuntimeError('La importación falló: '+str(info))
        if status=='COMPLETED':break
        if time.monotonic()-started>3600:raise RuntimeError('La importación sigue activa; revisar el identificador registrado.')
        time.sleep(20)
    data,_=request('/codesystems/'+short_name+'/versions')
    versions=[v for v in data['items'] if str(v.get('effectiveDate'))==expected]
    if len(versions)!=1:raise RuntimeError(f'No aparece una única versión {expected}: {data}')
    state['imports'][label]['version']=versions[0]
    save('verified_'+label)
try:
    branch,_=request('/branches/MAIN')
    system,_=request('/codesystems/SNOMEDCT')
    versions,_=request('/codesystems/SNOMEDCT/versions')
    if branch['path']!='MAIN' or branch['locked'] or system['shortName']!='SNOMEDCT' or versions['items']:
        raise RuntimeError('El servidor no tiene la rama base vacía esperada.')
    systems,_=request('/codesystems')
    if not any(s['shortName']=='SNOMEDCT' and s['branchPath']=='MAIN' for s in systems['items']):
        raise RuntimeError('El sistema base aún no figura en el listado de Snowstorm.')
    rf2('international',root/'snomed/SnomedCT_InternationalRF2_PRODUCTION_20261001T120000Z.zip','MAIN','SNOMEDCT','20261001')
    save('creating_spanish_branch')
    request('/codesystems',{'shortName':'SNOMEDCT-ES','branchPath':'MAIN/SNOMEDCT-ES','dependantVersionEffectiveTime':20261001})
    rf2('spanish',root/'snomed/SnomedCT_SpanishRelease-es_PRODUCTION_20261110T120000Z.zip','MAIN/SNOMEDCT-ES','SNOMEDCT-ES','20261110')
    save('completed',state='completed')
except Exception as e:
    save('interrupted',state='interrupted',error=str(e))
    raise
