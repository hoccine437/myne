"""Tests staged Python safely with compile/import checks; no package installation."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import subprocess,sys
@dataclass
class TestResult: name:str; passed:bool; output:str=''
class TestRunner:
 def __init__(self,root):self.root=Path(root)
 def run(self,manifest_id:str)->list[TestResult]:
  stage=self.root/'.zerion/evolution/staging'/manifest_id
  results=[]
  for p in stage.rglob('*.py'):
   r=subprocess.run([sys.executable,'-m','py_compile',str(p)],capture_output=True,text=True,timeout=15)
   results.append(TestResult(f'compile:{p.relative_to(stage)}',r.returncode==0,(r.stderr or r.stdout)[-1000:]))
  # Existing regression suite is optional and never installed automatically.
  test=self.root/'tests/test_phase4.py'
  if test.exists():
   r=subprocess.run([sys.executable,'-c','from tests.test_phase4 import test_phase4; test_phase4()'],cwd=self.root,capture_output=True,text=True,timeout=30)
   results.append(TestResult('regression:phase4',r.returncode==0,(r.stderr or r.stdout)[-1000:]))
  hardening=self.root/'tests/test_hardening.py'
  if hardening.exists():
   r=subprocess.run([sys.executable,str(hardening)],cwd=self.root,capture_output=True,text=True,timeout=30)
   results.append(TestResult('regression:hardening',r.returncode==0,(r.stderr or r.stdout)[-1000:]))
  return results
