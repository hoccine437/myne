"""Typed, goal-level contracts for the Android control layer."""
from __future__ import annotations
from dataclasses import dataclass,field
@dataclass(frozen=True)
class Capability:
 name:str; available:bool; permission:str=''; description:str=''
@dataclass(frozen=True)
class DeviceState:
 battery:str='unknown'; network:str='unknown'; foreground_app:str='unknown'; screen:str='unknown'; capabilities:tuple[str,...]=()
@dataclass(frozen=True)
class PhoneAction:
 capability:str; arguments:tuple[str,...]=(); consequential:bool=False; expected:str=''
@dataclass
class PhonePlan:
 goal:str; actions:list[PhoneAction]=field(default_factory=list); rationale:str=''
@dataclass(frozen=True)
class ActionResult:
 success:bool; message:str; data:str=''; verified:bool=False
