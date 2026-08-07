import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config,speech
def test_voice_only():
 assert config.VOICE_PROVIDER=='gemini'
 assert 'OfflineVoice' not in Path('speech.py').read_text()
 oldkey,oldmodel=config.GEMINI_API_KEY,config.GEMINI_TTS_MODEL
 try:
  config.GEMINI_API_KEY='';assert speech.speech_status()=='Speech: disabled.'
  config.GEMINI_API_KEY='key';config.GEMINI_TTS_MODEL='not-a-tts-model';assert speech.speech_status()=='Speech: disabled.'
 finally:config.GEMINI_API_KEY,config.GEMINI_TTS_MODEL=oldkey,oldmodel
if __name__=='__main__':test_voice_only()
