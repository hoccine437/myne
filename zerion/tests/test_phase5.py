import tempfile
from pathlib import Path
from evolution.analyzer import CapabilityAnalyzer
from evolution.engine import EvolutionEngine
from evolution.manifest import is_protected
from evolution.rollback import RollbackEngine
def test_phase5():
 with tempfile.TemporaryDirectory() as d:
  root=Path(d); (root/'tests').mkdir(); (root/'tests/test_phase4.py').write_text('def test_phase4(): pass')
  e=EvolutionEngine(root); assert isinstance(e.analyze()['findings'],list); assert is_protected('main.py')
  try:e.prepare('bad',{'main.py':'x=1'})
  except PermissionError:pass
  else:raise AssertionError('protected core accepted')
  m,review,results=e.prepare('add safe module',{'extensions/example.py':'"""safe"""\nvalue: int = 1\n'})
  assert review.approved and all(x.passed for x in results)
  try:e.deploy(m,results,False)
  except PermissionError:pass
  else:raise AssertionError('deployment lacked approval')
  ident=e.deploy(m,results,True); assert (root/'extensions/example.py').exists(); RollbackEngine(root).rollback(ident);assert not (root/'extensions/example.py').exists()
