"""Provider-agnostic execution registry. Providers are adapters, not cognition."""
from __future__ import annotations
from abc import ABC,abstractmethod
from .models import ExecutionRequest,ExecutionOutcome,ResourceState
class ExecutionProvider(ABC):
 name:str
 @abstractmethod
 def available(self,state:ResourceState)->bool:...
 @abstractmethod
 def execute(self,request:ExecutionRequest)->ExecutionOutcome:...
class ProviderRegistry:
 def __init__(self):self._providers={}
 def register(self,provider:ExecutionProvider):self._providers[provider.name]=provider
 def candidates(self,state):return [p for p in self._providers.values() if p.available(state)]
