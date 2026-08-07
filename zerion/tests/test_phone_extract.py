import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from phone.extract import PhoneIntentExtractor
def test_extract():
 e=PhoneIntentExtractor();assert e.extract('call +1 555 123 4567').parameters['number']=='+15551234567'
 assert e.extract('sms +15551234567: hello').missing==()
 assert e.extract('turn flashlight on').parameters['enabled']=='on'
 assert e.extract('call Bob').missing==('phone number',)
if __name__=='__main__':test_extract()
