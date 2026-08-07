import tempfile
from pathlib import Path
from knowledge.database import Database
from knowledge.manager import KnowledgeManager
from memory.long_term import LongTermMemory
from learning.experience import Experience,ExperienceStore
from learning.reflection import reflect
from skills.manager import SkillManager
def test_phase4():
 with tempfile.TemporaryDirectory() as d:
  m=KnowledgeManager(Database(Path(d)/'x.db')); LongTermMemory(m).remember('User prefers Python on Termux','preference',['python','termux'],.9,.9)
  assert m.retrieve_context('Python Termux')
  ExperienceStore(m).record(Experience(goal='test',final_result='passed'))
  assert 'What worked' in reflect('test','passed').content
  assert SkillManager().select('debug python code').name=='software_engineering'
