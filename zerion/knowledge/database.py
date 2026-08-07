"""Crash-safe SQLite storage for Phase 4. Standard library only."""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "zerion_knowledge.db"

class Database:
 def __init__(self, path: Path|str=DB_PATH): self.path=Path(path); self._init()
 def _connect(self):
  c=sqlite3.connect(self.path, timeout=5); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c
 def _init(self):
  with self._connect() as c:
   c.execute("""CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, layer TEXT NOT NULL, category TEXT NOT NULL, content TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}', importance REAL NOT NULL DEFAULT .5, confidence REAL NOT NULL DEFAULT .7, created REAL NOT NULL, accessed REAL NOT NULL, uses INTEGER NOT NULL DEFAULT 0, fingerprint TEXT UNIQUE)""")
   c.execute("CREATE INDEX IF NOT EXISTS idx_records_layer_category ON records(layer,category)")
   try: c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(content, tags, content='records', content_rowid='id')")
   except sqlite3.OperationalError: pass
 def save(self, *, layer:str, category:str, content:str, tags:list[str]|None=None, metadata:dict[str,Any]|None=None, importance:float=.5, confidence:float=.7, fingerprint:str|None=None)->int:
  """Persist one record without sharing mutable caller defaults between calls."""
  now=time.time(); tags = tags or []; metadata = metadata or {}
  with self._connect() as c:
   cur=c.execute("INSERT OR IGNORE INTO records(layer,category,content,tags,metadata,importance,confidence,created,accessed,fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?)",(layer,category,content,json.dumps(tags),json.dumps(metadata),importance,confidence,now,now,fingerprint))
   rid=cur.lastrowid
   if rid:
    try:c.execute("INSERT INTO records_fts(rowid,content,tags) VALUES(?,?,?)",(rid,content," ".join(tags)))
    except sqlite3.OperationalError:pass
    return rid
   if fingerprint is None:
    return 0
   existing=c.execute("SELECT id FROM records WHERE fingerprint=?",(fingerprint,)).fetchone()
   return int(existing[0]) if existing else 0
 def query(self, sql:str, args:tuple=()):
  with self._connect() as c:return [dict(x) for x in c.execute(sql,args)]
 def update(self, sql:str,args:tuple=()):
  with self._connect() as c:c.execute(sql,args)
