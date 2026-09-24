"""Validate real loader argument resolution without allocating 4B weights."""
import sys,types
import nagi.api as api
import pytest

@pytest.mark.parametrize('kwargs,expected',[
 ({},(api.BIG_REVISION,api.BIG_BASE_REVISION,api.BIG_TEMPERATURE)),
 ({'max_input_tokens':2048},(api.BIG_REVISION,api.BIG_BASE_REVISION,api.BIG_TEMPERATURE)),
 ({'repo':'custom/repo'},(None,None,1.0)),
 ({'revision':'custom-rev','base_revision':'base-rev','temperature':1.2},('custom-rev','base-rev',1.2)),
])
def test_big_release_defaults_and_overrides(monkeypatch,kwargs,expected):
 calls={}
 class Model:
  def merge_and_unload(self):calls['merged']=True;return self
  def to(self,dev):calls['device']=dev;return self
  def eval(self):calls['eval']=True;return self
 class Factory:
  @staticmethod
  def from_pretrained(repo,**kw):calls['base']=kw;return Model()
 class Tok:
  @staticmethod
  def from_pretrained(repo,**kw):calls['tokenizer']=kw;return object()
 class Peft:
  @staticmethod
  def from_pretrained(base,path):calls['adapter_path']=path;return base
 transformers=types.ModuleType('transformers');transformers.AutoModelForCausalLM=Factory;transformers.AutoTokenizer=Tok
 peft=types.ModuleType('peft');peft.PeftModel=Peft
 huggingface_hub=types.ModuleType('huggingface_hub');huggingface_hub.hf_hub_download=lambda *a,**kw: None
 for name,module in [('transformers',transformers),('peft',peft),('huggingface_hub',huggingface_hub)]:monkeypatch.setitem(sys.modules,name,module)
 def snapshot(repo,**kw):calls['adapter']=kw;return '/tmp/adapter'
 huggingface_hub.snapshot_download=snapshot
 monkeypatch.setattr(api,'Nagi',lambda model,**kw:kw)
 result=api.load_big(device='cpu',**kwargs)
 assert calls['adapter']['revision']==expected[0]
 assert calls['base']['revision']==calls['tokenizer']['revision']==expected[1]
 assert result['temperature']==expected[2]
 assert result['max_input_tokens']==kwargs.get('max_input_tokens',4096)
 assert calls['eval'] and calls['merged']
