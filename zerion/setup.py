"""Idempotent first-run preparation for Zerion Lite."""
from __future__ import annotations
import importlib.util, os, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REQUIRED={'requests':'requests','dotenv':'python-dotenv'}
REQUIRED_DIRS=('memory','constitution','providers','tools','tests')
def termux():return 'com.termux' in os.environ.get('PREFIX','')
def missing_packages():return [pkg for module,pkg in REQUIRED.items() if importlib.util.find_spec(module) is None]
def ensure_packages(install=True):
 missing=missing_packages()
 if missing and install:
  subprocess.run([sys.executable,'-m','pip','install','-r',str(ROOT/'requirements.txt')],check=False)
 return missing_packages()
def ensure_env():
 path=ROOT/'.env'
 if not path.exists():
  path.write_text('LLM_PROVIDER=gemini\nGEMINI_API_KEY=replace_with_key\nGEMINI_MODEL=gemini-3-flash-lite\nVOICE_ENABLED=true\nVOICE_PROVIDER=gemini\nVOICE_NAME=Charon\n',encoding='utf8');return 'created'
 return 'preserved'
def run():
 print('Zerion Lite setup')
 print('Python:',sys.version.split()[0], 'OK' if sys.version_info>=(3,10) else 'UNSUPPORTED (need 3.10+)')
 if sys.version_info<(3,10):return 2
 missing=ensure_packages();print('Python packages:', 'OK' if not missing else 'missing: '+', '.join(missing))
 env=ensure_env();print('.env:',env)
 missing_dirs=[d for d in REQUIRED_DIRS if not (ROOT/d).is_dir()];print('Project structure:', 'OK' if not missing_dirs else 'missing: '+', '.join(missing_dirs))
 writable=os.access(ROOT,os.W_OK);print('Project writable:',writable)
 try:
  from constitution.constitution import ConstitutionEngine
  print('Constitution integrity:',ConstitutionEngine.verify_lock())
 except Exception as exc:print('Constitution integrity: FAILED -',exc)
 print('Platform:', 'Termux' if termux() else 'non-Termux')
 commands=['termux-media-player','termux-battery-status','termux-clipboard-get','termux-telephony-call']
 available=[x for x in commands if shutil.which(x)];print('Termux API commands:', ', '.join(available) if available else 'none (optional)')
 print('Gemini speech requires GEMINI_API_KEY, a TTS-capable GEMINI_TTS_MODEL, and an audio player.')
 print('Setup complete. Configure GEMINI_API_KEY in .env for Gemini text and speech.')
 return 0
if __name__=='__main__':raise SystemExit(run())
