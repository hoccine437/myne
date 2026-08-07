from __future__ import annotations
class CapabilityQuality:
 def __init__(self):self._metrics={}
 def update(self,name,success,latency=0.,cost=0.,confidence=.5):
  m=self._metrics.setdefault(name,{'uses':0,'successes':0,'latency':0.,'cost':0.,'confidence':.5})
  m['uses']+=1;m['successes']+=int(success); n=m['uses'];m['latency']+=(latency-m['latency'])/n;m['cost']+=(cost-m['cost'])/n;m['confidence']=(m['confidence']+confidence)/2;m['reliability']=m['successes']/n;return m
 def get(self,name):return self._metrics.get(name,{})
 def weak(self):return [k for k,v in self._metrics.items() if v.get('uses',0)>=3 and v.get('reliability',1)<.5]
