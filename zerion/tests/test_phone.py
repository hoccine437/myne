import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phone.engine import PhoneIntelligence
from phone.models import PhoneAction,PhonePlan
def test_phone():
 phone=PhoneIntelligence();plan=phone.plan('call someone')
 assert isinstance(plan.actions,list)
 results=phone.execute(PhonePlan('call',[PhoneAction('telephony',consequential=True)]),False)
 assert not results[0].success and 'Approval' in results[0].message
if __name__=='__main__':test_phone()
