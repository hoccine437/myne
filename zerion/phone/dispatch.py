"""Supervised bridge from validated PhoneIntent to existing controllers."""
from __future__ import annotations
from constitution import Constitution
from intelligence.experience import ExperienceEngine,ExecutionExperience
from intelligence.reflection import ReflectionEngine
from intelligence.world import WorldModel
from intelligence.projects import ProjectContinuity
from .extract import PhoneIntent
from .models import ActionResult
from .verifier import ExecutionVerifier
class PhoneDispatcher:
 def __init__(self,controllers, verifier=None, constitution=None, experience=None, reflection=None, world=None, projects=None):
  self.controllers=controllers;self.verifier=verifier or ExecutionVerifier();self.constitution=constitution or Constitution()
  self.experience=experience or ExperienceEngine();self.reflection=reflection or ReflectionEngine();self.world=world or WorldModel();self.projects=projects or ProjectContinuity()
 def dispatch(self,goal:str,intent:PhoneIntent,approved:bool=False)->ActionResult:
  if intent.missing:return ActionResult(False,'Missing required information: '+', '.join(intent.missing)+'.')
  consequential=intent.capability in {'clipboard_write','torch','telephony','sms','camera','open_url','notification','media','volume','vibrate'}
  decision=self.constitution.evaluate('execute_shell' if consequential else 'reason')
  if not decision.allowed:return ActionResult(False,decision.reason)
  if consequential and not approved:return ActionResult(False,f'Approval required for {intent.capability}.')
  try: result=self._call(intent)
  except (KeyError,ValueError) as exc:result=ActionResult(False,f'Invalid phone request: {exc}')
  verified=self.verifier.verify(result)
  self._record(goal,intent,verified)
  return verified
 def _call(self,intent):
  p=intent.parameters;c=intent.capability
  if c=='telephony':return self.controllers[c].call(p['number'])
  if c=='sms':return self.controllers[c].sms(p['number'],p['message'])
  if c=='open_url':return self.controllers[c].open_url(p['url'])
  if c=='torch':return self.controllers[c].torch(p['enabled']=='on')
  if c=='clipboard_write':return self.controllers[c].write(p['text'])
  if c=='clipboard_read':return self.controllers[c].read()
  if c=='volume':return self.controllers[c].set_level(p.get('stream','music'),p['level'])
  if c=='vibrate':return self.controllers[c].vibrate(p.get('duration_ms',150))
  if c=='battery_state':return self.controllers[c].battery()
  if c=='wifi':return self.controllers[c].wifi()
  if c=='media':return self.controllers[c].control(p['op'])
  raise ValueError(f'unsupported capability {c}')
 def _record(self,goal,intent,result):
  self.experience.record(ExecutionExperience('phone dispatch',goal,intent.capability,path=[intent.capability],success=result.success,lessons=result.message,confidence=.7 if result.success else .3))
  from intelligence.models import ExecutionOutcome,DecisionRecord
  reflection=self.reflection.reflect(goal,ExecutionOutcome(result.success,result.message,provider='phone',verified=result.verified),DecisionRecord(goal,'phone',(), 'supervised phone dispatch',.7))
  self.world.link(f'goal:{goal}','phone_result',intent.capability)
  self.projects.save(goal,goal,'phone dispatch complete' if result.success else 'phone dispatch failed',decisions=[reflection.change])
