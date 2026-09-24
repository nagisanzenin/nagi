import math
import pytest
import torch
from nagi.huge import NagiHuge
class Model:
 def eval(self):return self
class Tokenizer:
 def apply_chat_template(self,messages,**kw):return 'PROMPT'
 def encode(self,text,**kw):return [1,2,3]+([10+ord(text[-1])-65] if text!='PROMPT' else [])
def test_boundary_and_no_silent_truncation():
 n=NagiHuge(Model(),Tokenizer(),max_tokens=3)
 ids,slots,keys=n.encode('evidence',{'q':{'type':'choice','instructions':'Select','criteria':{'x':'x','y':'y'}}},'q')
 assert ids==[1,2,3] and slots==[10,11] and keys==['x','y']
 n.max_tokens=2
 with pytest.raises(ValueError,match='No truncation'):n.encode('evidence',{'q':{'type':'noul','instructions':'Yes?'}},'q')
@pytest.mark.parametrize('temp',[0,-1,float('nan'),float('inf')])
def test_invalid_temperature(temp):
 with pytest.raises(ValueError):NagiHuge(Model(),Tokenizer(),temperature=temp)
