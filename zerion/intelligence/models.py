from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any
@dataclass(frozen=True)
class ResourceState:
 cpu:float=0.; memory:float=0.; battery:float=-1.; charging:bool=False; network:str='unknown'; temperature:float=-1.; permissions:tuple[str,...]=()
@dataclass(frozen=True)
class DecisionRecord:
 goal:str; selected:str; alternatives:tuple[str,...]; reason:str; score:float
@dataclass(frozen=True)
class ExecutionRequest:
 goal:str; capability:str; payload:dict[str,Any]=field(default_factory=dict); consequential:bool=False
@dataclass(frozen=True)
class ExecutionOutcome:
 success:bool; message:str; latency:float=0.; resource_cost:float=0.; provider:str=''; verified:bool=False
