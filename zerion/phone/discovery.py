from .adapter import TermuxAdapter
from .models import Capability,DeviceState
_COMMANDS={'clipboard_read':'termux-clipboard-get','clipboard_write':'termux-clipboard-set','open_url':'termux-open-url','battery_state':'termux-battery-status','notification':'termux-notification','media':'termux-media-player','camera':'termux-camera-photo','torch':'termux-torch','wifi':'termux-wifi-connectioninfo','telephony':'termux-telephony-call','sms':'termux-sms-send','share':'termux-share','volume':'termux-volume'}
class CapabilityDiscovery:
 def __init__(self,adapter=None):self.adapter=adapter or TermuxAdapter()
 def capabilities(self):return [Capability(k,self.adapter.has(v),'Termux:API where applicable',f'Uses {v}') for k,v in _COMMANDS.items()]
 def state(self):
  available=tuple(c.name for c in self.capabilities() if c.available)
  battery=self.adapter.run('termux-battery-status').data if 'battery_state' in available else 'unavailable'
  network=self.adapter.run('termux-wifi-connectioninfo').data if 'wifi' in available else 'unavailable'
  return DeviceState(battery=battery[:500],network=network[:500],capabilities=available)
