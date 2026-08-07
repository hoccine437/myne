from __future__ import annotations
from dataclasses import dataclass,field
STAGES=('unknown','learning','basic','intermediate','advanced','expert','master','improving')
@dataclass(frozen=True)
class Capability:
 name:str; knowledge:str=''; reasoning:str=''; execution:str=''; verification:str=''; experience_count:int=0; confidence:float=.2; stage:str='unknown'; tags:tuple[str,...]=field(default_factory=tuple)
@dataclass(frozen=True)
class CapabilityGap:
 goal:str; missing:str; learnable:bool=True
