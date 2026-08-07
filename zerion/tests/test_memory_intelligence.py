import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memory.intelligence import MemoryIntelligence
from knowledge.database import Database
from knowledge.manager import KnowledgeManager
def test_memory_intelligence():
 with tempfile.TemporaryDirectory() as d:
  m=MemoryIntelligence(KnowledgeManager(Database(Path(d)/'x.db')))
  assert m.inference('offline preference',.65,['request'],['evidence'])
  assert m.procedure('test flow',['tool'],[], 'result')
  assert m.episodic('goal','ctx',['a'],'done','reuse',.7)
  assert m.retrieve('offline preference')
  assert 'archived' in m.consolidate()
if __name__=='__main__':test_memory_intelligence()
