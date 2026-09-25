import math
import pytest
import torch
from nagi.enormous import NagiEnormous
class Model:
 def eval(self):return self
class Tokenizer:
 def __init__(self,chat='PROMPT'):self.chat=chat;self.kw=None
 def apply_chat_template(self,messages,**kw):self.kw=kw;return self.chat
 def encode(self,text,**kw):return [1,2,3]+([10+ord(text[-1])-65] if text!=self.chat else [])
Q={'q':{'type':'choice','instructions':'Select','criteria':{'x':'x','y':'y'}}}
def test_boundary_and_no_silent_truncation():
 tok=Tokenizer();n=NagiEnormous(Model(),tok,max_tokens=3)
 ids,slots,keys=n.encode('evidence',Q,'q')
 assert ids==[1,2,3] and slots==[10,11] and keys==['x','y']
 assert tok.kw['enable_thinking'] is False and tok.kw['add_generation_prompt'] is True
 n.max_tokens=2
 with pytest.raises(ValueError,match='No truncation'):n.encode('evidence',{'q':{'type':'noul','instructions':'Yes?'}},'q')
def test_closed_empty_think_block_is_accepted():
 n=NagiEnormous(Model(),Tokenizer('<|im_start|>assistant\n<think>\n\n</think>\n\n'))
 assert n.encode('evidence',Q,'q')[1]==[10,11]
def test_open_think_block_is_rejected():
 n=NagiEnormous(Model(),Tokenizer('<|im_start|>assistant\n<think>\n'))
 with pytest.raises(ValueError,match='thinking block open'):n.encode('evidence',Q,'q')
@pytest.mark.parametrize('temp',[0,-1,float('nan'),float('inf')])
def test_invalid_temperature(temp):
 with pytest.raises(ValueError):NagiEnormous(Model(),Tokenizer(),temperature=temp)
