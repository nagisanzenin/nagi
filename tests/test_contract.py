import pytest
import torch
from nagi.api import Nagi
from nagi.model import ScoreHead

def test_score_head_batched_variable_options():
 head=ScoreHead(8).eval()
 out=head(torch.randn(2,8),torch.randn(2,7,8),torch.ones(2,7),torch.randn(2,5,8),torch.tensor([0,1]))
 assert out.shape==(2,5) and torch.isfinite(out).all()

def test_big_rejects_unsupported_cardinality_before_forward():
 class Model(torch.nn.Module):
  def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.zeros(1))
  def forward(self,*args,**kwargs):raise AssertionError('should not run model')
 class Tokenizer:
  def encode(self,x,**kwargs):return [ord(x)]
 api=Nagi(Model(),Tokenizer(),kind='letter')
 with pytest.raises(ValueError,match='at most 26'):
  api.system_one('state',{'q':{'type':'choice','criteria':{str(i):str(i) for i in range(77)}}})

def test_experimental_high_k_keeps_option_77_and_normalizes():
 from types import SimpleNamespace
 from nagi.render import EXTENDED_SYMBOLS
 class Tokenizer:
  def encode(self,s,**kwargs):return list(s.encode('ascii'))
  def decode(self,x,**kwargs):return bytes(x).decode('ascii')
  def __call__(self,s,**kwargs):return {'input_ids':torch.tensor([self.encode(s)])}
 class Model(torch.nn.Module):
  def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.zeros(1))
  def forward(self,input_ids):
   logits=torch.zeros(1,input_ids.shape[1],128)
   logits[0,-1,ord(EXTENDED_SYMBOLS[76])]=12
   return SimpleNamespace(logits=logits)
 api=Nagi(Model(),Tokenizer(),kind='letter',max_options=78)
 answer=api.system_one('requested code 76',{'q':{'type':'choice','instructions':'Match code','criteria':{f'k{i}':f'Code {i}' for i in range(77)}}})['answers']['q']
 assert len(answer['probabilities'])==77 and answer['choice']=='k76'
 assert abs(sum(answer['probabilities'].values())-1)<1e-9

def test_multi_token_decision_symbol_is_rejected():
 class Model(torch.nn.Module):
  def __init__(self):super().__init__();self.p=torch.nn.Parameter(torch.zeros(1))
 class Tokenizer:
  def encode(self,s,**kwargs):return [1,2]
 api=Nagi(Model(),Tokenizer(),kind='letter')
 with pytest.raises(ValueError,match='single tokens'):
  api.system_one('x',{'q':{'type':'choice','criteria':{'a':'yes','b':'no'}}})
