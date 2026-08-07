import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from constitution.constitution import ConstitutionEngine,ConstitutionIntegrityError
from constitution.registry import ProtectedFileRegistry
from constitution.evolution import ProtectedEvolution
def test_engine():
 laws=ConstitutionEngine.load();assert laws is ConstitutionEngine.load() and ConstitutionEngine.get_law('CORE-001')
 assert ConstitutionEngine.verify_lock() and ConstitutionEngine.is_protected('main.py')
 assert ConstitutionEngine.can_execute('modify','main.py',True)[0] is False
 assert ConstitutionEngine.can_execute('deploy','extensions/a.py',False)[0] is False
 assert ConstitutionEngine.resolve_conflict(laws[:2]).priority==100
 assert ProtectedFileRegistry(Path('.')).entries()
 with tempfile.TemporaryDirectory() as d:
  root=Path(d); (root/'tests').mkdir(); (root/'tests/test_phase4.py').write_text('def test_phase4(): pass')
  protected=ProtectedEvolution(root)
  manifest, review, results=protected.prepare('safe addition',{'extensions/a.py':'value: int = 1\n'})
  assert review.approved and all(item.passed for item in results)
  try: protected.prepare('blocked',{'main.py':'x=1\n'})
  except PermissionError: pass
  else: raise AssertionError('protected evolution was staged')
 with tempfile.TemporaryDirectory() as d:
  text=Path(d)/'constitution.txt'; lock=Path(d)/'constitution.lock'; text.write_text('tampered');lock.write_text('wrong')
  old_text,old_lock,old_cache=ConstitutionEngine.TEXT,ConstitutionEngine.LOCK,ConstitutionEngine._cache
  ConstitutionEngine.TEXT,ConstitutionEngine.LOCK,ConstitutionEngine._cache=text,lock,None
  try:
   try: ConstitutionEngine.load()
   except ConstitutionIntegrityError: pass
   else: raise AssertionError('tampered constitution accepted')
  finally: ConstitutionEngine.TEXT,ConstitutionEngine.LOCK,ConstitutionEngine._cache=old_text,old_lock,old_cache
 # The protected-core manifest is independently required at normal startup.
 old_protected=ConstitutionEngine.PROTECTED_LOCK
 ConstitutionEngine.PROTECTED_LOCK=Path('/missing/protected.lock')
 try:
  try: ConstitutionEngine.verify_lock()
  except ConstitutionIntegrityError: pass
  else: raise AssertionError('missing protected lock accepted')
 finally: ConstitutionEngine.PROTECTED_LOCK=old_protected
if __name__=='__main__':test_engine()
