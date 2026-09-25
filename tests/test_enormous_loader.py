"""Verify ENORMOUS base/adapter pins without allocating 27B weights."""
import sys,types
import pytest
from nagi import enormous

def _fake_stack(monkeypatch,calls):
 class Model:
  config=types.SimpleNamespace(use_cache=True)
  def eval(self):return self
 class Factory:
  @staticmethod
  def from_pretrained(repo,**kwargs):calls['base']=(repo,kwargs);return Model()
 class Tokenizer:
  @staticmethod
  def from_pretrained(repo,**kwargs):calls['tokenizer']=(repo,kwargs);return object()
 class Peft:
  @staticmethod
  def from_pretrained(base,path,**kwargs):calls['adapter']=(path,kwargs);return base
 hub=types.ModuleType('huggingface_hub')
 def snapshot(repo,**kw):calls['snapshot']=(repo,kw);return '/adapter'
 hub.snapshot_download=snapshot
 tf=types.ModuleType('transformers');tf.AutoModelForCausalLM=Factory;tf.AutoTokenizer=Tokenizer
 peft=types.ModuleType('peft');peft.PeftModel=Peft
 for name,m in [('huggingface_hub',hub),('transformers',tf),('peft',peft)]:monkeypatch.setitem(sys.modules,name,m)

def test_refuses_while_revision_unpinned(monkeypatch):
 calls={};_fake_stack(monkeypatch,calls)
 monkeypatch.setattr(enormous,'ENORMOUS_REVISION',None)
 with pytest.raises(RuntimeError,match='unpinned'):enormous.load_enormous(device='cuda')
 with pytest.raises(RuntimeError,match='unpinned'):enormous.load_enormous(revision='a'*40,device='cuda')
 assert calls=={}

def test_exact_release_load_path(monkeypatch):
 calls={};_fake_stack(monkeypatch,calls)
 monkeypatch.setattr(enormous,'ENORMOUS_REVISION','0'*40)
 out=enormous.load_enormous(device='cuda')
 assert calls['base'][0]==calls['tokenizer'][0]==enormous.ENORMOUS_BASE=='Qwen/Qwen3.8-27B'
 assert calls['base'][1]['revision']==calls['tokenizer'][1]['revision']==enormous.ENORMOUS_BASE_REVISION
 assert len(enormous.ENORMOUS_BASE_REVISION)==40
 assert calls['snapshot'][0]==enormous.ENORMOUS_REPO and calls['snapshot'][1]['revision']==enormous.ENORMOUS_REVISION
 assert calls['base'][1]['attn_implementation']=='eager'
 assert str(calls['base'][1]['dtype'])=='torch.bfloat16'
 assert calls['adapter'][1]['is_trainable'] is False
 assert out.max_tokens==4096 and out.temperature==1 and not out.model.config.use_cache
