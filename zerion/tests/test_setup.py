import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import setup
def test_setup():
 assert setup.termux() is False
 with tempfile.TemporaryDirectory() as d:
  old=setup.ROOT;setup.ROOT=Path(d)
  try:
   assert setup.ensure_env()=='created';content=(Path(d)/'.env').read_text();assert 'VOICE_PROVIDER=gemini' in content
   assert setup.ensure_env()=='preserved'
  finally:setup.ROOT=old
if __name__=='__main__':test_setup()
