"""Connected local semantic graph stored beside existing knowledge, never replacing it."""
from knowledge.database import Database
class WorldModel:
 def __init__(self,db=None):
  self.db=db or Database()
  with self.db._connect() as c:c.execute('CREATE TABLE IF NOT EXISTS graph_edges(source TEXT, relation TEXT, target TEXT, weight REAL DEFAULT 1, UNIQUE(source,relation,target))')
 def link(self,source,relation,target,weight=1.):
  with self.db._connect() as c:c.execute('INSERT INTO graph_edges VALUES(?,?,?,?) ON CONFLICT(source,relation,target) DO UPDATE SET weight=excluded.weight',(source,relation,target,weight))
 def related(self,node,limit=12):return self.db.query('SELECT source,relation,target,weight FROM graph_edges WHERE source=? OR target=? ORDER BY weight DESC LIMIT ?',(node,node,limit))
