import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intelligence.models import *
from intelligence.registry import *
from intelligence.resolver import ExecutionResolver
from intelligence.world import WorldModel
from knowledge.database import Database
class Fake(ExecutionProvider):
 def __init__(self,name,ok):self.name=name;self.ok=ok
 def available(self,state):return True
 def execute(self,request):return ExecutionOutcome(self.ok,self.name)
def test_intelligence():
 reg=ProviderRegistry();reg.register(Fake('bad',False));reg.register(Fake('good',True))
 resolver=ExecutionResolver(reg,{'bad':{'reliability':.9},'good':{'reliability':.5}})
 out,decision=resolver.execute(ExecutionRequest('goal','x'),ResourceState())
 assert out.success and out.provider=='good' and decision.selected=='bad'
 # Consequential work never falls through after a provider response.
 out,_=resolver.execute(ExecutionRequest('goal','x',consequential=True),ResourceState());assert not out.success
 with tempfile.TemporaryDirectory() as d:
  world=WorldModel(Database(Path(d)/'x.db'));world.link('project:a','uses','capability:b');assert world.related('project:a')
if __name__=='__main__':test_intelligence()
