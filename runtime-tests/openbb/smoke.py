import json,socket
# Deny outbound connections: import/build/ASGI exercise must remain offline.
def denied(*args,**kwargs): raise RuntimeError('Network disabled for local qualification')
socket.create_connection=denied
_connect=socket.socket.connect
def local_connect(self,address):
    if isinstance(address,tuple) and address[0] in ('127.0.0.1','::1'):
        return _connect(self,address)
    return denied(self,address)
socket.socket.connect=local_connect
from openbb import obb
from openbb_core.provider.registry import Registry
from openbb_core.app.constants import OPENBB_DIRECTORY
assert 'runtime-tests' in str(OPENBB_DIRECTORY)
assert obb.system.version
assert isinstance(obb.reference,dict)
print('SDK',repr(obb),'version',obb.system.version,'reference_count',len(obb.reference))
r=Registry()
print('Registry',repr(r))
from openbb_core.api.rest_api import app,system
from fastapi.testclient import TestClient
with TestClient(app) as client:
    schema=client.get('/openapi.json'); assert schema.status_code==200
    paths=schema.json()['paths']
    print('paths',json.dumps(list(paths)))
    for suffix in ['/system','/coverage/providers','/coverage/commands','/coverage/command_model']:
        path=system.api_settings.prefix+suffix
        response=client.get(path)
        assert response.status_code==200,(path,response.status_code,response.text)
        print('GET',path,response.status_code,response.text[:500])
    assert client.get('/nonexistent-route').status_code==404
print('LOCAL_SMOKE_PASS')
