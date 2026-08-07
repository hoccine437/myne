import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cognition.reasoning import CognitiveReasoningEngine
from knowledge.database import Database
from knowledge.manager import KnowledgeManager
from constitution.constitution import ConstitutionEngine
def test_reasoning():
 with tempfile.TemporaryDirectory() as d:
  engine=CognitiveReasoningEngine(KnowledgeManager(Database(Path(d)/'x.db')));result=engine.reason('I am building an offline AI')
  assert result.inferences and result.inferences[0].status=='hypothesis' and 0<result.confidence<1
 assert ConstitutionEngine.get_law('REA-001') and 'You are Zerion' in Path('prompt.txt').read_text()
if __name__=='__main__':test_reasoning()
