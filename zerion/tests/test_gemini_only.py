import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from providers.base import ProviderError
from providers import router
def test_gemini_only():
 assert config.LLM_PROVIDER=='gemini' and config.GEMINI_MODEL=='gemini-3-flash-lite'
 try:router.call_llm('s','u',provider_name='gpt')
 except ProviderError as e:assert 'Only Gemini' in str(e)
 else:raise AssertionError('retired provider was accepted')
if __name__=='__main__':test_gemini_only()
