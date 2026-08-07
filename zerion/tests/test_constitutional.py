import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from constitution import Constitution
from cognition import CognitiveEngine
from cognition.modes import select_mode
from knowledge.database import Database
from knowledge.manager import KnowledgeManager
from cognition.curiosity import CuriosityEngine
def test_constitutional_cognition():
 assert Constitution().evaluate('modify','main.py').allowed is False
 assert Constitution().evaluate('deploy','extensions/x.py').requires_approval is True
 assert select_mode('debug Python code').name=='programming'
 with tempfile.TemporaryDirectory() as d:
  curiosity=CuriosityEngine(KnowledgeManager(Database(Path(d)/'knowledge.db')))
  gap=curiosity.detect('obscure novel problem'); assert gap is not None
  assert curiosity.record(gap)>0
  assert curiosity.detect('obscure novel problem') is not None # low confidence gap remains honest
 proposal=CognitiveEngine().propose_capability('goal','missing connector')
 assert proposal['requires_approval'] and proposal['action']=='propose'
if __name__=='__main__':test_constitutional_cognition()
