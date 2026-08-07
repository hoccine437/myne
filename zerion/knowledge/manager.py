"""Public Knowledge Manager: indexed, ranked persistent reusable facts."""
from __future__ import annotations
import hashlib,re
from .database import Database
from .search import KnowledgeSearch
class KnowledgeManager:
 def __init__(self, db=None): self.db=db or Database(); self.searcher=KnowledgeSearch(self.db)
 def store(self, content:str, category:str='note', tags:list[str]|None=None, importance:float=.5, confidence:float=.7, metadata:dict|None=None, layer:str='knowledge')->int:
  content=content.strip(); tags=tags or []; fp=hashlib.sha256((layer+'|'+category+'|'+content.lower()).encode()).hexdigest()
  return self.db.save(layer=layer,category=category,content=content,tags=tags,importance=max(0,min(1,importance)),confidence=max(0,min(1,confidence)),metadata=metadata or {},fingerprint=fp)
 def retrieve_context(self, query:str, limit:int=5)->str:
  found=self.searcher.search(query,limit)
  return '\n'.join(f"[{x['layer']}/{x['category']}, confidence {x['confidence']:.0%}] {x['content']}" for x in found)
