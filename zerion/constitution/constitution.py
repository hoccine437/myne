"""Cached, integrity-checked constitutional authority with no mutable law path."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import re
@dataclass(frozen=True)
class Law: id:str; priority:int; title:str; description:str; examples:str
class ConstitutionIntegrityError(RuntimeError):pass
class ConstitutionEngine:
 _cache=None
 ROOT=Path(__file__).resolve().parent
 TEXT=ROOT/'constitution.txt'; LOCK=ROOT/'constitution.lock'; PROTECTED_LOCK=ROOT/'protected.lock'
 PROTECTED=('constitution/constitution.txt','constitution/constitution.py','constitution/constitution.lock','main.py')
 @classmethod
 def _digest(cls):return sha256(cls.TEXT.read_bytes()).hexdigest()
 @classmethod
 def _protected_digests(cls):
  return {path:sha256((cls.ROOT.parent/path).read_bytes()).hexdigest() for path in cls.PROTECTED}
 @classmethod
 def verify_lock(cls):
  try: expected=cls.LOCK.read_text(encoding='utf8').strip()
  except OSError as exc:raise ConstitutionIntegrityError(f'Constitution lock unavailable: {exc}')
  if not expected or expected != cls._digest():raise ConstitutionIntegrityError('Constitution text integrity mismatch; owner approval/relock is required.')
  try: protected=json.loads(cls.PROTECTED_LOCK.read_text(encoding='utf8'))
  except (OSError,json.JSONDecodeError) as exc:raise ConstitutionIntegrityError(f'Protected-core lock unavailable: {exc}')
  if protected != cls._protected_digests():raise ConstitutionIntegrityError('Protected-core integrity mismatch; owner maintenance is required.')
  return True
 @classmethod
 def load(cls):
  if cls._cache is None:
   cls.verify_lock(); text=cls.TEXT.read_text(encoding='utf8'); cls._cache=cls._parse(text)
   if not cls.validate():raise ConstitutionIntegrityError('Constitution contains no valid laws.')
  return cls._cache
 @classmethod
 def reload(cls,owner_approved=False):
  if not owner_approved:raise PermissionError('Owner approval is required to reload the Constitution.')
  cls._cache=None;return cls.load()
 @staticmethod
 def _parse(text):
  pattern=r'ID:\s*([^|]+)\|\s*Priority:\s*(\d+)\s*\|\s*Title:\s*(.+)\nDescription:\s*(.+)\nExamples:\s*(.+)'
  return tuple(Law(a.strip(),int(b),c.strip(),d.strip(),e.strip()) for a,b,c,d,e in re.findall(pattern,text))
 @classmethod
 def validate(cls):return bool(cls._cache) and all(l.id and l.priority>0 for l in cls._cache)
 @classmethod
 def get_law(cls,law_id):return next((x for x in cls.load() if x.id==law_id),None)
 @classmethod
 def get_all_laws(cls):return cls.load()
 @classmethod
 def is_protected(cls,path):
  value=Path(path).as_posix();return value in cls.PROTECTED
 @classmethod
 def can_execute(cls,action,target='',approved=False):
  if action in {'modify','deploy','delete'} and cls.is_protected(target):return False,'Target is Constitution-protected.'
  if action in {'modify','deploy','delete','execute_shell','execute_python'} and not approved:return False,'Explicit owner approval is required.'
  return True,'Permitted by Constitution.'
 @classmethod
 def resolve_conflict(cls,laws):return max(laws,key=lambda x:x.priority) if laws else None
