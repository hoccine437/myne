from __future__ import annotations
import ast
from dataclasses import dataclass
from .manifest import UpgradeManifest,is_protected
@dataclass
class Review: approved:bool; issues:list[str]
class CodeReviewer:
 def review(self,manifest:UpgradeManifest, changes:dict[str,str])->Review:
  issues=[]
  try:manifest.validate()
  except Exception as e:issues.append(str(e))
  if set(changes)!=set(manifest.files):issues.append('staged files do not match manifest')
  for path,text in changes.items():
   if is_protected(path):issues.append(f'protected: {path}');continue
   if len(text.splitlines())>300:issues.append(f'{path}: exceeds 300 lines')
   if path.endswith('.py'):
    try:ast.parse(text)
    except SyntaxError as e:issues.append(f'{path}: syntax error: {e.msg}')
   if 'subprocess.run(' in text and 'shell=True' in text:issues.append(f'{path}: unsafe shell=True')
  return Review(not issues,issues)
