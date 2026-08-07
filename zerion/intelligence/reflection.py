from dataclasses import dataclass
@dataclass(frozen=True)
class StructuredReflection:
 worked:str;failed:str;why:str;change:str;update_memory:bool;ranking_delta:float
class ReflectionEngine:
 def reflect(self,goal,outcome,decision):
  ok=outcome.success;return StructuredReflection('provider completed request' if ok else '', '' if ok else outcome.message,'selected '+decision.selected, 'reuse method' if ok else 'lower provider/capability confidence',bool(outcome.message),.05 if ok else -.1)
