"""Integrity-checked shared JSON contracts and single-writer paper state."""
from pathlib import Path
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib,json,os,re,tempfile
import time

class SkillError(ValueError):
    pass

def require(condition,message):
    if not condition:
        raise SkillError(message)

def decimal(value):
    require(not isinstance(value,bool) and value is not None,"Expected a finite decimal")
    try:
        result=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc:
        raise SkillError("Invalid decimal") from exc
    require(result.is_finite(),"Nonfinite decimal rejected")
    return result

def utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    try:
        result=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
    except (ValueError,TypeError) as exc:
        raise SkillError("Expected ISO8601 timestamp with timezone") from exc
    require(result.tzinfo is not None,"Naive timestamps rejected; supply timezone")
    return result.astimezone(timezone.utc)

def iso(value=None):
    return utc(value).isoformat().replace('+00:00','Z')

def _encode(obj):
    try:
        return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (TypeError,ValueError) as exc:
        raise SkillError("Artifact must contain finite JSON values; use decimal strings for money") from exc

def digest(obj):
    return hashlib.sha256(_encode(obj)).hexdigest()

def read_json(path):
    try:
        p=Path(path)
        require(p.stat().st_size<=64*1024*1024,"JSON input exceeds64MiB")
        return json.loads(p.read_text(encoding='utf-8'),parse_constant=lambda x:(_ for _ in ()).throw(SkillError('Nonfinite JSON')))
    except (OSError,ValueError) as exc:
        raise SkillError(f"Cannot read JSON {path}: {exc}") from exc

def read_envelope(path,kind):
    obj=read_json(path)
    require(isinstance(obj,dict),"Artifact must be an object")
    require(type(obj.get('schema_version')) is int and obj['schema_version']==1,"Unsupported schema version")
    require(obj.get('kind')==kind,"Wrong artifact kind")
    require(isinstance(obj.get('data'),dict) and isinstance(obj.get('inputs'),dict),"Invalid data/inputs shape")
    require(isinstance(obj.get('created_at'),str),"Missing artifact timestamp")
    utc(obj['created_at'])
    actual=digest({k:v for k,v in obj.items() if k!='digest'})
    require(obj.get('digest')==actual,"Artifact digest mismatch")
    return obj


def replace_with_windows_retry(temporary, path):
    """Publish an already-written file with bounded retries for Windows sharing errors."""
    for delay in (.025, .05, .10, .20, .40, None):
        try:
            temporary.replace(path)
            return
        except PermissionError as error:
            # Windows readers can temporarily deny atomic replacement.
            if delay is None or getattr(error, 'winerror', None) not in (5, 32, 33):
                raise
            time.sleep(delay)


class Workspace:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.state=self.root/'trader'
        require(self.state.resolve().is_relative_to(self.root),"State directory escapes workspace")
        self.state.mkdir(exist_ok=True)

    def _path(self,kind):
        require(isinstance(kind,str) and re.fullmatch(r'[a-z][a-z0-9_-]*',kind),"Invalid artifact kind")
        p=self.state/(kind+'.json')
        require(not p.is_symlink(),"Symlink artifact rejected")
        return p

    def read(self,kind):
        return read_envelope(self._path(kind),kind)

    @property
    def config(self):
        c=self.read('config')['data']
        require(c.get('mode')=='paper',"Only paper mode is supported")
        return c

    def write(self,kind,data,inputs=None,now=None):
        p=self._path(kind)
        require(isinstance(data,dict),"Artifact data must be an object")
        require(inputs is None or isinstance(inputs,dict),"Artifact inputs must be an object")
        obj={'schema_version':1,'kind':kind,'created_at':iso(now),'inputs':inputs or {},'data':data}
        obj['digest']=digest(obj)
        payload=_encode(obj)
        temp=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.state,prefix='.'+kind+'-',suffix='.tmp',delete=False) as f:
                temp=Path(f.name);f.write(payload);f.flush();os.fsync(f.fileno())
            os.replace(temp,p)
        finally:
            if temp and temp.exists():temp.unlink()
        return obj

    @contextmanager
    def lock(self,name='writer'):
        require(isinstance(name,str) and re.fullmatch(r'[a-z][a-z0-9_-]*',name),'Invalid lock name')
        p=self.state/('.'+name+'.lock')
        try:
            fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError as exc:
            raise SkillError(f'Workspace lock {name} is held; inspect its owner before manually clearing an abandoned lock') from exc
        try:
            with os.fdopen(fd,'w') as f:f.write(json.dumps({'pid':os.getpid(),'at':iso()}))
            yield
        finally:
            p.unlink(missing_ok=True)
