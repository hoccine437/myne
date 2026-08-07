"""Gemini-only provider router preserving the public call_llm API."""
import config
from providers.base import ProviderError
_instance=None
def _get_provider():
 global _instance
 if _instance is None:
  from providers.gemini import GeminiProvider
  _instance=GeminiProvider()
 return _instance
def available_providers():return ['gemini'] if _get_provider().is_configured() else []
def call_llm(system_prompt,user_prompt,provider_name=None):
 if provider_name and provider_name!='gemini':raise ProviderError('Only Gemini is supported in this release.')
 provider=_get_provider()
 if not provider.is_configured():raise ProviderError('GEMINI_API_KEY is not set. Configure it in .env before sending requests.')
 return provider.call(system_prompt,user_prompt,timeout=config.REQUEST_TIMEOUT)
