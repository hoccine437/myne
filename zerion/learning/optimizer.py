from knowledge.database import Database
class MemoryOptimizer:
 def __init__(self,db=None):self.db=db or Database()
 def consolidate(self)->int:
  """Only removes exact duplicate fingerprints; valuable unique records stay."""
  # UNIQUE fingerprint prevents duplicates at insertion; prune only empty low-value stale entries.
  before=self.db.query("SELECT count(*) AS n FROM records WHERE length(trim(content))=0")
  self.db.update("DELETE FROM records WHERE length(trim(content))=0")
  return before[0]['n']
