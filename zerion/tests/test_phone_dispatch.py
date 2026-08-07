import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phone.dispatch import PhoneDispatcher
from phone.extract import PhoneIntent
from phone.models import ActionResult
class C:
 def __init__(self,ok=True):self.ok=ok;self.called=False
 def call(self,n):self.called=True;return ActionResult(self.ok,'called')
def test_dispatch():
 c=C();d=PhoneDispatcher({'telephony':c})
 complete=PhoneIntent('telephony',{'number':'+15551234567'},())
 assert 'Missing' in d.dispatch('g',PhoneIntent('telephony',{},('phone number',)),True).message
 assert 'Approval' in d.dispatch('g',complete,False).message and not c.called
 assert d.dispatch('g',complete,True).success and c.called
 bad=PhoneDispatcher({'telephony':C(False)}).dispatch('bad',complete,True);assert not bad.success
if __name__=='__main__':test_dispatch()
