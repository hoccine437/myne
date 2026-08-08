"""Goal-first Android orchestration with constitutional approval gates."""
from __future__ import annotations
from constitution import Constitution
from learning.engine import LearningEngine
from .controllers import ClipboardController,MediaController,SystemController,CommunicationController,CameraController,NotificationController,VolumeController,VibrateController,DeviceReadController
from .discovery import CapabilityDiscovery
from .models import ActionResult,PhoneAction,PhonePlan
from .verifier import ExecutionVerifier
from .extract import PhoneIntentExtractor
from .dispatch import PhoneDispatcher
class PhoneIntelligence:
 def __init__(self):
  self.discovery=CapabilityDiscovery(); self.constitution=Constitution();self.verify=ExecutionVerifier();self.learning=LearningEngine()
  self.controllers={'clipboard_read':ClipboardController(),'clipboard_write':ClipboardController(),'media':MediaController(),'open_url':SystemController(),'torch':SystemController(),'telephony':CommunicationController(),'sms':CommunicationController(),'camera':CameraController(),'notification':NotificationController()}
  self.controllers.update({'volume':VolumeController(),'vibrate':VibrateController(),'battery_state':DeviceReadController(),'wifi':DeviceReadController()})
  self.extractor=PhoneIntentExtractor();self.dispatcher=PhoneDispatcher(self.controllers,self.verify,self.constitution)
  # first-class physical body: full action lifecycle + live state + audit
  from .manager import PhoneBodyManager
  self.body=PhoneBodyManager(self.dispatcher,self.discovery,self.constitution)
 def supervised_intent(self,goal:str,approved:bool=False):
  """Extract then dispatch only complete, explicitly approved phone requests."""
  intent=self.extractor.extract(goal)
  return self.dispatcher.dispatch(goal,intent,approved) if intent else None
 def plan(self,goal:str)->PhonePlan:
  """Create a proposal. Selection is capability-aware and no action runs here."""
  text=goal.lower(); available={c.name for c in self.discovery.capabilities() if c.available}; actions=[]
  intents=[(('copy','clipboard'),'clipboard_read'),(('paste','clipboard'),'clipboard_write'),(('music','pause','play','media'),'media'),(('flashlight','torch'),'torch'),(('call','phone'),'telephony'),(('sms','text message'),'sms'),(('camera','photo'),'camera'),(('open','browser','website'),'open_url')]
  for words,cap in intents:
   if any(w in text for w in words) and cap in available:
    actions.append(PhoneAction(cap,consequential=cap in {'clipboard_write','torch','telephony','sms','camera','open_url'},expected=f'{cap} command completes'))
    break
  rationale='Capability-aware proposal derived from the user goal.' if actions else 'No permitted local capability was discovered; explain available permissions/integrations.'
  return PhonePlan(goal,actions,rationale)
 def execute(self,plan:PhonePlan, approved:bool=False)->list[ActionResult]:
  results=[]
  for action in plan.actions:
   decision=self.constitution.evaluate('execute_shell' if action.consequential else 'reason')
   if action.consequential and not approved:
    results.append(ActionResult(False,f"Approval required for {action.capability}."));continue
   if not decision.allowed:results.append(ActionResult(False,decision.reason));continue
   results.append(ActionResult(False,f'{action.capability} needs explicit arguments from a supervised caller.'))
  return results
 def record(self,goal:str,result:ActionResult)->None:
  self.learning.learn_task(goal,result.message,tools=['phone'],failures=[] if result.success else [result.message])
