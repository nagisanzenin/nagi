import torch
import pytest
from types import SimpleNamespace
from nagi.api import Nagi

class CharacterTokenizer:
 def encode(self,s,**kwargs):return list(s.encode('ascii'))
 def decode(self,ids,**kwargs):return bytes(ids).decode('ascii')
 def __call__(self,s,**kwargs):return {'input_ids':torch.tensor([self.encode(s)])}
class TailModel(torch.nn.Module):
 def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.zeros(1));self.seen=None
 def forward(self,input_ids):
  self.seen=bytes(input_ids[0].tolist()).decode('ascii');z=torch.zeros(1,input_ids.shape[1],128)
  z[0,-1,ord('B' if 'TARGET_END' in self.seen else 'A')]=10
  return SimpleNamespace(logits=z)

def test_expanded_cap_preserves_late_evidence_and_short_prompt():
 model=TailModel();tok=CharacterTokenizer();questions={'q':{'type':'choice','instructions':'Read the record','criteria':{'no':'absent','yes':'present'}}}
 old=Nagi(model,tok,kind='letter',max_input_tokens=768);new=Nagi(model,tok,kind='letter',max_input_tokens=4096)
 short='TARGET_END';a=old.system_one(short,questions);prompt=model.seen;b=new.system_one(short,questions)
 assert a==b and model.seen==prompt
 long='irrelevant '*100+'TARGET_END'
 assert old.system_one(long,questions)['answers']['q']['choice']=='no'
 assert new.system_one(long,questions)['answers']['q']['choice']=='yes'
 assert len(model.seen)<=4096

@pytest.mark.parametrize('value',[True,0,127,2048.5])
def test_invalid_caps(value):
 with pytest.raises(ValueError,match='max_input_tokens'):Nagi(TailModel(),CharacterTokenizer(),kind='letter',max_input_tokens=value)

def test_smol_dynamic_state_preserves_fixed_option_shape():
 class Tok:
  def __call__(self,text,**kw):
   n=kw['max_length'] if kw['padding']=='max_length' else min(len(text),kw['max_length'])
   return {'input_ids':torch.ones(1,n,dtype=torch.long),'attention_mask':torch.ones(1,n,dtype=torch.long)}
 class Model(torch.nn.Module):
  def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.zeros(1));self.state_max_len=2048;self.option_max_len=64
  def forward(self,ids,mask,option_ids,option_mask,qtype):
   assert ids.shape[1]<2048
   assert option_ids.shape==option_mask.shape==(1,2,64)
   return torch.zeros(1,2)
 n=Nagi(Model(),Tok(),dynamic_state_padding=True)
 r=n.system_one('short',{'q':{'type':'choice','instructions':'Pick','criteria':{'a':'A','b':'B'}}})
 assert r['answers']['q']['probabilities']=={'a':.5,'b':.5}
