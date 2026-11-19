import os, sys, json, time, socket, threading, subprocess, importlib.metadata, platform
from pathlib import Path
ROOT = Path(r'E:\coding\code\Trade\MiroFish')
OUT = Path(__file__).resolve().parent
PY = sys.executable

def isolate():
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False
    for key in ('LLM_API_KEY','ZEP_API_KEY','OPENAI_API_KEY','ZEP_API_URL'):
        os.environ.pop(key, None)
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    real_connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1','localhost','::1'):
            raise RuntimeError('Runtime evidence prohibits outbound connections')
        return real_connect(sock, address)
    socket.socket.connect = local_connect
    sys.path.insert(0, str(ROOT / 'backend'))
    sys.path.insert(0, str(ROOT))
    import app.utils.logger as logger
    logger.LOG_DIR = str(OUT / 'app-logs')

def http_run():
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    import httpx, fitz
    from werkzeug.serving import make_server
    provider_calls = []
    class Provider(BaseHTTPRequestHandler):
        failure = False
        def log_message(self,*a): pass
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            provider_calls.append({'path':self.path,'model':payload['model'],'messages':payload['messages']})
            if self.failure:
                self.send_response(401); self.send_header('Content-Type','application/json'); self.send_header('x-request-id','local-provider-denied'); self.end_headers()
                self.wfile.write(b'{"error":{"message":"PRIVATE-FAKE-PROVIDER-BODY","type":"authentication_error"}}'); return
            ontology = {'entity_types':[{'name':'Resident','description':'Local resident','attributes':[]}], 'edge_types':[{'name':'discusses_with','description':'Discusses local news','source_targets':[{'source':'Resident','target':'Resident'}],'attributes':[]}], 'analysis_summary':'Deterministic local fake provider output; no inference.'}
            result = {'id':'chatcmpl-local-fixture','object':'chat.completion','created':1,'model':'local-fake-model','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(ontology)}}]}
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(result).encode())
    fake = ThreadingHTTPServer(('127.0.0.1',0),Provider)
    threading.Thread(target=fake.serve_forever,daemon=True).start()
    from app.config import Config
    Config.LLM_API_KEY = 'local-fixture-not-a-credential'
    Config.LLM_MODEL_NAME = 'local-fake-model'
    Config.LLM_BASE_URL = f'http://127.0.0.1:{fake.server_port}/v1'
    Config.ZEP_API_KEY = None
    Config.UPLOAD_FOLDER = str(OUT / 'uploads')
    from app.models.project import ProjectManager
    ProjectManager.PROJECTS_DIR = str(OUT / 'projects')
    from app.services.simulation_manager import SimulationManager
    SimulationManager.SIMULATION_DATA_DIR = str(OUT / 'simulations')
    from app import create_app
    app = create_app()
    server = make_server('127.0.0.1',0,app,threaded=True)
    serving = threading.Thread(target=server.serve_forever,daemon=True); serving.start()
    base = f'http://127.0.0.1:{server.server_port}'
    checks = []
    session = httpx.Client(trust_env=False)
    def check(method,path,status,**kwargs):
        res = session.request(method,base+path,timeout=20,**kwargs)
        data = res.json()
        checks.append({'method':method,'path':path,'status':res.status_code,'response':data})
        assert res.status_code == status, (path,res.status_code,res.text)
        return data
    try:
        assert check('GET','/health',200)['status']=='ok'
        assert check('GET','/api/graph/project/list',200)['count']==0
        check('GET','/api/graph/project/proj_missing',404)
        check('POST','/api/graph/ontology/generate',400)
        check('POST','/api/graph/ontology/generate',400,data={'simulation_requirement':'Test'})
        check('POST','/api/graph/ontology/generate',400,data={'simulation_requirement':'Test'},files={'files':('bad.exe',b'blocked')})
        pdf = fitz.open(); page = pdf.new_page(); page.insert_text((40,60),'PDF sentinel: residents discuss local transit.'); pdfbytes = pdf.tobytes(); pdf.close()
        generated = check('POST','/api/graph/ontology/generate',200,data={'simulation_requirement':'Model local transit discussion','project_name':'Runtime deterministic local test'},files=[('files',('source.txt','TXT sentinel: Alice discusses transit.\nनमस्ते'.encode(),'text/plain')),('files',('source.md',b'# Markdown sentinel\nBob discusses transit.','text/markdown')),('files',('source.pdf',pdfbytes,'application/pdf'))])
        project_id = generated['data']['project_id']; assert len(generated['data']['files'])==3
        project = check('GET',f'/api/graph/project/{project_id}',200)['data']; assert project['status']=='ontology_generated'
        text = ProjectManager.get_extracted_text(project_id)
        assert all(s in text for s in ('TXT sentinel','Markdown sentinel','PDF sentinel','नमस्ते'))
        assert all(s in provider_calls[0]['messages'][-1]['content'] for s in ('TXT sentinel','Markdown sentinel','PDF sentinel'))
        assert any(e['name']=='Person' for e in project['ontology']['entity_types'])
        assert project['ontology']['edge_types'][0]['name']=='DISCUSSES_WITH'
        saved_path = Path(ProjectManager.PROJECTS_DIR) / project_id / 'project.json'
        assert json.loads(saved_path.read_text(encoding='utf-8'))['status']=='ontology_generated'
        check('POST',f'/api/graph/project/{project_id}/reset',200)
        check('DELETE',f'/api/graph/project/{project_id}',200)
        check('GET',f'/api/graph/project/{project_id}',404)
        Provider.failure = True
        failed = check('POST','/api/graph/ontology/generate',502,data={'simulation_requirement':'Expected provider denial'},files={'files':('fail.txt',b'Local failure fixture')})
        assert 'PRIVATE-FAKE-PROVIDER-BODY' not in json.dumps(failed)
        failed_id=failed['data']['project_id']
        assert check('GET',f'/api/graph/project/{failed_id}',200)['data']['status']=='failed'
        check('DELETE',f'/api/graph/project/{failed_id}',200)
        assert check('GET','/api/graph/project/list',200)['count']==0
    finally:
        server.shutdown(); server.server_close(); serving.join(5)
        fake.shutdown(); fake.server_close()
    assert not serving.is_alive()
    result={'status':'passed','transport':'real loopback HTTP / Werkzeug WSGI server','checks':checks,'provider_call_count':len(provider_calls),'provider_boundary':'deterministic local OpenAI-compatible HTTP fixture; real SDK + ontology generator; no real model inference','zep_boundary':'not called','shutdown':'server stopped and listening socket closed'}
    (OUT/'http-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'HTTP lifecycle passed: {len(checks)} requests, {len(provider_calls)} local fake provider calls; shutdown confirmed')

if __name__=='__main__':
    if len(sys.argv)>1:
        isolate()
        if sys.argv[1]=='backend':
            import pytest
            raise SystemExit(pytest.main([str(ROOT/'backend'/'tests'),'-q','-p','no:cacheprovider','--basetemp',str(OUT/'pytest-temp')]))
        elif sys.argv[1]=='root':
            import unittest
            suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
            raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
        else: http_run()
    else:
        meta={'started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'python':sys.version,'platform':platform.platform(),'commit':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),'git_status_before':subprocess.check_output(['git','-C',str(ROOT),'status','--short'],text=True),'versions':{},'runs':[]}
        for package in ('Flask','pytest','openai','zep-cloud','PyMuPDF','camel-oasis','camel-ai'):
            try: meta['versions'][package]=importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: meta['versions'][package]='not installed'
        (OUT/'pip-freeze.txt').write_text(subprocess.check_output([PY,'-m','pip','freeze'],text=True),encoding='utf-8')
        for mode in ('backend','root','http'):
            cmd=[PY,str(Path(__file__).resolve()),mode]; started=time.monotonic()
            env=os.environ.copy(); env['PYTHONIOENCODING']='utf-8'
            result=subprocess.run(cmd,cwd=ROOT/'backend',capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,timeout=180)
            (OUT/f'{mode}.log').write_text(result.stdout+'\nSTDERR:\n'+result.stderr,encoding='utf-8')
            meta['runs'].append({'mode':mode,'command':cmd,'cwd':str(ROOT/'backend'),'exit_code':result.returncode,'seconds':round(time.monotonic()-started,2),'log':str(OUT/f'{mode}.log')})
            print(mode,result.returncode,result.stdout[-350:],flush=True)
        meta['git_status_after']=subprocess.check_output(['git','-C',str(ROOT),'status','--short'],text=True)
        (OUT/'result.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
