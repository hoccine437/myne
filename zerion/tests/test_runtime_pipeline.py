import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import llm,api
def test_pipeline():
 calls=[]
 def fake(system,user):
  calls.append((system,user));return '{"intent":"chat","parameters":{},"text":"User Safety: safe","memory_update":null}'
 old=llm.api.call_llm;llm.api.call_llm=fake
 try:
  output=llm.get_llm_output('hi',{})
 finally:llm.api.call_llm=old
 assert len(calls)==1 and output['text']=='Hello. How can I help?'
 # Compatibility shim passes arguments into router facade.
 old_router=api._call_llm;api._call_llm=lambda s,u,provider_name=None:'router response'
 try:assert api.call_llm('s','u')=='router response'
 finally:api._call_llm=old_router
if __name__=='__main__':test_pipeline()
