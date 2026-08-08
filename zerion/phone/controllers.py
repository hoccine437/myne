"""Capability controllers. They expose methods, never execute unapproved goals."""
from __future__ import annotations
from .adapter import TermuxAdapter
from .models import ActionResult
class PhoneController:
 def __init__(self,adapter=None):self.adapter=adapter or TermuxAdapter()
class ClipboardController(PhoneController):
 def read(self):return self.adapter.run('termux-clipboard-get')
 def write(self,text):return self.adapter.run('termux-clipboard-set',text)
class MediaController(PhoneController):
 def control(self,operation):return self.adapter.run('termux-media-player',operation)
class SystemController(PhoneController):
 def torch(self,enabled):return self.adapter.run('termux-torch','on' if enabled else 'off')
 def open_url(self,url):return self.adapter.run('termux-open-url',url)
class CommunicationController(PhoneController):
 def call(self,number):return self.adapter.run('termux-telephony-call',number)
 def sms(self,number,message):return self.adapter.run('termux-sms-send','-n',number,message)
class CameraController(PhoneController):
 def capture(self,path):return self.adapter.run('termux-camera-photo','-c','0',path,timeout=20)
class NotificationController(PhoneController):
 def notify(self,title,content):return self.adapter.run('termux-notification','--title',title,'--content',content)

class VolumeController(PhoneController):
 def set_level(self,stream,level):return self.adapter.run('termux-volume',str(stream),str(level))
class VibrateController(PhoneController):
 def vibrate(self,duration_ms=150):return self.adapter.run('termux-vibrate','-d',str(int(duration_ms)))
class DeviceReadController(PhoneController):
 def battery(self):return self.adapter.run('termux-battery-status')
 def wifi(self):return self.adapter.run('termux-wifi-connectioninfo')
