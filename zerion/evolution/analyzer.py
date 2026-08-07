"""Read-only AST/size analysis; deliberately no network or code execution."""
from __future__ import annotations
import ast
from dataclasses import dataclass,asdict
from pathlib import Path
from .manifest import PROTECTED_PATHS
@dataclass
class Finding: category:str; path:str; detail:str; priority:int
class CapabilityAnalyzer:
 def __init__(self,root:str|Path):self.root=Path(root).resolve()
 def analyze(self)->list[Finding]:
  findings=[]; seen={}
  for p in self.root.rglob('*.py'):
   if any(x in p.parts for x in ('.git','.zerion','__pycache__')):continue
   rel=p.relative_to(self.root).as_posix()
   try: source=p.read_text(encoding='utf8'); tree=ast.parse(source)
   except (OSError,SyntaxError) as e:findings.append(Finding('syntax',rel,str(e),10));continue
   lines=len(source.splitlines())
   if lines>300:findings.append(Finding('complexity',rel,f'{lines} lines; consider split',4))
   for node in ast.walk(tree):
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and len(node.body)>45:findings.append(Finding('complexity',rel,f'{node.name} has {len(node.body)} statements',3))
   key=' '.join(source.split())
   if key in seen:findings.append(Finding('duplicate',rel,f'duplicates {seen[key]}',6))
   else:seen[key]=rel
  return sorted(findings,key=lambda f:f.priority,reverse=True)
 def report(self)->dict:return {'root':str(self.root),'findings':[asdict(x) for x in self.analyze()]}
