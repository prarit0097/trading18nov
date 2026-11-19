import unittest,subprocess,sys,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NAMES=['workflow','market','news','entry','exit','size','risk','paper','backtest','timemachine','world','report']
class SkillsTests(unittest.TestCase):
 def test_skill_metadata_and_runnable_wrappers(self):
  for n in NAMES:
   with self.subTest(skill=n):
    p=ROOT/'skills'/('crypto-'+n)
    self.assertTrue((p/'SKILL.md').is_file())
    t=(p/'SKILL.md').read_text(encoding='utf-8')
    self.assertTrue(t.startswith('---\nname: crypto-'+n+'\n'))
    self.assertIn('description: Use when',t)
    q=subprocess.run([sys.executable,str(p/'scripts'/f'{n}.py'),'--help'],capture_output=True,text=True,encoding='utf-8')
    self.assertEqual(q.returncode,0,q.stderr)
    for link in re.findall(r'\]\(([^)]+)\)',t):
     self.assertTrue((p/link).exists(),link)

if __name__=='__main__':unittest.main()
