from __future__ import annotations
import re
from .database import Database
from .ranking import score

def tokens(s:str)->set[str]: return set(re.findall(r"[\w'-]{2,}",s.lower()))
class KnowledgeSearch:
 def __init__(self, db:Database|None=None):self.db=db or Database()
 def search(self, query:str, limit:int=6, layers:list[str]|None=None)->list[dict]:
  q=tokens(query); rows=self.db.query("SELECT * FROM records" + (" WHERE layer IN (%s)" % ','.join('?'*len(layers)) if layers else ""),tuple(layers or ()))
  out=[]
  for r in rows:
   text=tokens(r['content']+' '+r['tags']+' '+r['category']); union=q|text
   rel=len(q&text)/len(union) if union else 0
   if rel or any(x in r['content'].lower() for x in q):
    r['tags']=__import__('json').loads(r['tags']); r['metadata']=__import__('json').loads(r['metadata']); r['score']=score(r,rel); out.append(r)
  out.sort(key=lambda x:x['score'],reverse=True)
  for r in out[:limit]:self.db.update("UPDATE records SET uses=uses+1,accessed=? WHERE id=?",(__import__('time').time(),r['id']))
  return out[:limit]
