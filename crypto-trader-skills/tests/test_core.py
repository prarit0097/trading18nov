import unittest,tempfile,json
from pathlib import Path
from crypto_skills.core import Workspace,SkillError,decimal,digest

class CoreTests(unittest.TestCase):
 def test_integrity_and_atomic_read(self):
  with tempfile.TemporaryDirectory() as t:
   w=Workspace(t);a=w.write('market',{'price':'1'})
   self.assertEqual(w.read('market')['digest'],a['digest'])
   p=Path(t)/'trader/market.json';v=json.loads(p.read_text());v['data']['price']='2';p.write_text(json.dumps(v))
   with self.assertRaises(SkillError):w.read('market')
 def test_nonfinite_and_bool_rejected(self):
  for v in [True,'NaN','Infinity']:
   with self.assertRaises(SkillError):decimal(v)
 def test_kind_and_lock(self):
  with tempfile.TemporaryDirectory() as t:
   w=Workspace(t)
   with self.assertRaises(SkillError):w.write('../escape',{})
   with w.lock():
    with self.assertRaises(SkillError):
     with w.lock():pass
 def test_missing_or_null_artifact_timestamp_rejected_even_with_valid_hash(self):
  with tempfile.TemporaryDirectory() as t:
   w=Workspace(t)
   for value in ('absent',None):
    obj=w.write('market',{'price':'1'})
    if value=='absent':obj.pop('created_at')
    else:obj['created_at']=value
    obj['digest']=digest({k:v for k,v in obj.items() if k!='digest'})
    (w.state/'market.json').write_text(json.dumps(obj))
    with self.assertRaises(SkillError):w.read('market')

if __name__=='__main__':unittest.main()
