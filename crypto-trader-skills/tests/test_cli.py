import unittest,tempfile,subprocess,sys,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from crypto_skills.cli import initialize
from crypto_skills.core import Workspace,SkillError
ROOT=Path(__file__).resolve().parents[1]

class CliTests(unittest.TestCase):
 def test_initialization_holds_single_writer_lock(self):
  with tempfile.TemporaryDirectory() as t:
   write=Workspace.write
   def checked_write(workspace,*args,**kwargs):
    with self.assertRaises(SkillError):
     with Workspace(t).lock():pass
    return write(workspace,*args,**kwargs)
   with patch.object(Workspace,'write',autospec=True,side_effect=checked_write):
    initialize(SimpleNamespace(workspace=t,input=None,now=None))
 def call(self,*args):
  return subprocess.run([sys.executable,str(ROOT/'run.py'),*args],capture_output=True,text=True,encoding='utf-8')
 def test_init_refuses_overwrite_and_status(self):
  with tempfile.TemporaryDirectory() as t:
   p=self.call('init','--workspace',t)
   self.assertEqual(p.returncode,0,p.stderr)
   self.assertEqual(json.loads(p.stdout)['data']['risk_budget'],None)
   self.assertNotEqual(self.call('init','--workspace',t).returncode,0)
   self.assertEqual(self.call('status','--workspace',t).returncode,0)
 def test_live_mode_rejected(self):
  with tempfile.TemporaryDirectory() as t:
   f=Path(t)/'input.json';f.write_text(json.dumps({'mode':'live'}))
   p=self.call('init','--workspace',t,'--input',str(f))
   self.assertEqual(p.returncode,2)
   self.assertIn('Only paper mode',json.loads(p.stderr)['error'])

if __name__=='__main__':unittest.main()
