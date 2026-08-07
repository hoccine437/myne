"""Supervised extraction only: never invents values or executes phone actions."""
from __future__ import annotations
from dataclasses import dataclass
import re
@dataclass(frozen=True)
class PhoneIntent:
 capability:str; parameters:dict[str,str]; missing:tuple[str,...]
class PhoneIntentExtractor:
 def extract(self,text:str)->PhoneIntent|None:
  t=text.strip();low=t.lower()
  if low.startswith('call '):
   number=re.search(r'\+?[0-9][0-9 -]{5,}',t);return PhoneIntent('telephony',{'number':number.group(0).replace(' ','').replace('-','')} if number else {},() if number else ('phone number',))
  if low.startswith('sms ') or low.startswith('text '):
   number=re.search(r'\+?[0-9][0-9 -]{5,}',t);message=re.search(r':\s*(.+)$',t)
   p={};
   if number:p['number']=number.group(0).replace(' ','').replace('-','')
   if message:p['message']=message.group(1).strip()
   missing=tuple(label for label,key in (('phone number','number'),('message','message')) if key not in p)
   return PhoneIntent('sms',p,missing)
  if 'flashlight' in low or 'torch' in low:return PhoneIntent('torch',{'enabled':'off' if 'off' in low else 'on' if 'on' in low else ''},() if ('on' in low or 'off' in low) else ('on or off state',))
  if low.startswith('open ') and re.search(r'https?://\S+',t):return PhoneIntent('open_url',{'url':re.search(r'https?://\S+',t).group(0)},())
  return None
