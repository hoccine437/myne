"""Small lifecycle adapter wiring existing intelligence records into each request."""
from __future__ import annotations
from .world import WorldModel
from .composition import CapabilityComposition
from .projects import ProjectContinuity
from .simulation import SimulationLayer
from .quality import CapabilityQuality
from .experience import ExperienceEngine,ExecutionExperience
from .reflection import ReflectionEngine
from .models import ExecutionRequest,ExecutionOutcome,DecisionRecord,ResourceState
from .registry import ExecutionProvider,ProviderRegistry
from .resolver import ExecutionResolver
from memory.intelligence import MemoryIntelligence
class _ReasoningProvider(ExecutionProvider):
 name='normal_reasoning'
 def available(self,state): return True
 def execute(self,request): return ExecutionOutcome(True,'planning-only provider')
class RuntimeIntelligence:
 def __init__(self):
  self.world=WorldModel();self.composition=CapabilityComposition();self.projects=ProjectContinuity()
  self.simulation=SimulationLayer();self.quality=CapabilityQuality();self.experiences=ExperienceEngine();self.reflections=ReflectionEngine()
  registry=ProviderRegistry();registry.register(_ReasoningProvider());self.resolver=ExecutionResolver(registry,self.quality._metrics)
  self.memory=MemoryIntelligence()
 def prepare(self,goal:str,records:list[dict]):
  composition=self.composition.compose(goal,records)
  prior=self.projects.resume(goal)
  request=ExecutionRequest(goal,'reasoning')
  simulation=self.simulation.simulate(request)
  _provider,decision=self.resolver.select(request,ResourceState())
  self.world.link(f'goal:{goal}','uses',f'composition:{composition["strategy"]}')
  for item in records[:3]:self.world.link(f'goal:{goal}','informed_by',f"capability:{item.get('id','unknown')}")
  memories=self.memory.retrieve(goal,goal,3)
  return {'composition':composition,'prior_projects':prior[:2],'simulation':simulation,'resolver_decision':decision,'memories':memories}
 def complete(self,goal:str,response:str,elapsed:float,records:list[dict]):
  outcome=ExecutionOutcome(bool(response),response[:300],elapsed,provider='llm',verified=bool(response))
  decision=DecisionRecord(goal,'llm',(), 'normal response lifecycle',self.quality.get('llm').get('reliability',.5))
  reflection=self.reflections.reflect(goal,outcome,decision)
  self.quality.update('llm',outcome.success,elapsed,0.,.65 if outcome.success else .3)
  self.experiences.record(ExecutionExperience('normal runtime',goal,' + '.join(x.get('category','capability') for x in records[:3]) or 'general reasoning',success=outcome.success,latency=elapsed,lessons=reflection.change,confidence=.65 if outcome.success else .3))
  self.world.link(f'goal:{goal}','produced',f'experience:{goal}')
  self.projects.save(goal,goal,'response completed',decisions=[reflection.change])
  self.memory.episodic(goal,'normal runtime',['llm'],response,reflection.change,.65 if outcome.success else .3)
  return reflection
