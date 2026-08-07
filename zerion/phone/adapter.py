"""Termux adapter: capability discovery and bounded, argument-list execution."""
from __future__ import annotations
import shutil,subprocess
from .models import ActionResult
class TermuxAdapter:
 def has(self, command:str)->bool:return shutil.which(command) is not None
 def run(self, command:str, *args:str, timeout:int=8)->ActionResult:
  if not self.has(command):return ActionResult(False,f'{command} is unavailable; install/authorize its Termux integration.')
  try:
   p=subprocess.run([command,*args],capture_output=True,text=True,timeout=timeout)
   output=(p.stdout+p.stderr).strip()[:4000]
   return ActionResult(p.returncode==0,output or ('Completed.' if p.returncode==0 else f'{command} failed.'),output)
  except subprocess.TimeoutExpired:return ActionResult(False,f'{command} timed out.')
  except OSError as exc:return ActionResult(False,f'{command} could not run: {exc}')
