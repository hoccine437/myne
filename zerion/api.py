"""Backward-compatible Gemini-only provider shim."""
from providers.router import call_llm as _call_llm
def call_gemini(system_prompt:str,user_prompt:str)->str:return _call_llm(system_prompt,user_prompt,provider_name='gemini')
def call_llm(system_prompt:str,user_prompt:str,provider_name=None,**kw)->str:return _call_llm(system_prompt,user_prompt,provider_name=provider_name,**kw)
