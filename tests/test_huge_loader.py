"""Verify released base/adapter pins without allocating 12B weights."""
import sys,types
from nagi import huge

def test_exact_release_load_path(monkeypatch):
 calls={}
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
 out=huge.load_huge(device='cuda')
 assert calls['base'][0]==calls['tokenizer'][0]==huge.HUGE_BASE
 assert calls['base'][1]['revision']==calls['tokenizer'][1]['revision']==huge.HUGE_BASE_REVISION
 assert calls['snapshot'][1]['revision']==huge.HUGE_REVISION and len(huge.HUGE_REVISION)==40
 assert calls['base'][1]['attn_implementation']=='eager'
 assert calls['adapter'][1]['is_trainable'] is False
 assert out.max_tokens==4096 and out.temperature==1 and not out.model.config.use_cache
