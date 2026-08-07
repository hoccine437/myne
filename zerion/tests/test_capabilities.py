import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from capabilities.manager import CapabilityManager
from capabilities.reasoning import CapabilityReasoner
from knowledge.database import Database
from knowledge.manager import KnowledgeManager
def test_capabilities():
 with tempfile.TemporaryDirectory() as d:
  manager=CapabilityManager(KnowledgeManager(Database(Path(d)/'db.sqlite')))
  context=CapabilityReasoner(manager).assess('solve a novel data issue')
  assert context.gap is not None
  manager.acquire('solve a novel data issue','Use validated CSV parsing',['data','csv'])
  assert manager.find('CSV parsing')
  manager.improve('CSV parsing','parse with validation',True,.8)
if __name__=='__main__':test_capabilities()
