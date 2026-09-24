"""Nagi-HUGE: the exact single-forward Gemma 12B benchmark readout."""
from __future__ import annotations
import math
import torch
HUGE_REPO='nagisanzeninz/Nagi-HUGE'
HUGE_REVISION='97b4b16f8ef25b08c5209219a731374b0f4edc27'
HUGE_BASE='google/gemma-4-12B-it'
HUGE_BASE_REVISION='707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7'
class NagiHuge:
    """Typed closed-set decisions, no generation or silent truncation.

    Choice is evaluated on the public suite. Score/noul reuse the same typed
    renderer; public-suite accuracy does not establish those tasks' quality.
    """
    def __init__(self,model,tokenizer,temperature=1.0,max_tokens=4096):
        if not math.isfinite(temperature) or temperature<=0:raise ValueError('temperature must be finite and positive')
        if not isinstance(max_tokens,int) or not 1<=max_tokens<=4096:raise ValueError('max_tokens must be between 1 and 4096')
        self.model=model.eval();self.tok=tokenizer;self.temperature=temperature;self.max_tokens=max_tokens
    def encode(self,state,questions,qid):
        from nagi.render import render_nagi_prompt
        prompt,keys=render_nagi_prompt({'state':state,'questions':questions},qid)
        if not 2<=len(keys)<=26:raise ValueError('Nagi-HUGE supports 2–26 options')
        chat=self.tok.apply_chat_template([{'role':'user','content':prompt}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        ids=self.tok.encode(chat,add_special_tokens=False)
        if len(ids)>self.max_tokens:raise ValueError(f'Input has {len(ids)} tokens; limit {self.max_tokens}. No truncation was applied.')
        slots=[]
        for j in range(len(keys)):
            combined=self.tok.encode(chat+chr(65+j),add_special_tokens=False)
            if len(combined)!=len(ids)+1 or combined[:-1]!=ids:raise ValueError('Answer boundary changes tokenization')
            slots.append(combined[-1])
        if len(set(slots))!=len(slots):raise ValueError('Answer slots collide')
        return ids,slots,keys
    @torch.inference_mode()
    def system_one(self,state,questions):
        if not isinstance(questions,dict) or not questions:raise ValueError('questions must be a nonempty dict')
        answers={};core=self.model.get_base_model() if hasattr(self.model,'get_base_model') else self.model
        text=core.model.language_model if hasattr(core.model,'language_model') else core.model
        device=next(self.model.parameters()).device
        for qid,q in questions.items():
            if not isinstance(q,dict) or q.get('type','choice') not in ('choice','score','noul'):raise ValueError('Supported question types: choice, score, noul')
            ids,slots,keys=self.encode(state,questions,qid)
            x=torch.tensor([ids],device=device);mask=torch.ones_like(x)
            last=text(input_ids=x,attention_mask=mask,use_cache=False).last_hidden_state[:,-1]
            z=torch.nn.functional.linear(last,core.get_output_embeddings().weight[torch.tensor(slots,device=device)])
            cap=getattr(core.config.get_text_config(),'final_logit_softcapping',None)
            if cap:z=cap*torch.tanh(z/cap)
            p=(z.float()/self.temperature).softmax(-1)[0].cpu().tolist();probs=dict(zip(keys,p))
            answer={'probabilities':probs,'confidence':max(p)};kind=q.get('type','choice')
            if kind=='score':answer['score']=sum(float(k)*v for k,v in probs.items())
            elif kind=='noul':answer['noul']=probs['true']
            else:answer['choice']=keys[max(range(len(p)),key=p.__getitem__)]
            answers[qid]=answer
        return {'answers':answers}
def load_huge(repo=HUGE_REPO,revision=None,device=None,temperature=1.0,max_tokens=4096):
    """Load pinned Gemma base plus unmerged HUGE adapter, matching evaluation.

    Downloads the public Gemma base from Hugging Face. CUDA BF16 was measured;
    other devices/precisions are not represented by the published H100 timings.
    """
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM,AutoTokenizer
    if repo==HUGE_REPO:revision=revision or HUGE_REVISION
    dev=device or ('cuda' if torch.cuda.is_available() else 'cpu')
    dtype=torch.bfloat16 if str(dev).startswith('cuda') else torch.float32
    tok=AutoTokenizer.from_pretrained(HUGE_BASE,revision=HUGE_BASE_REVISION)
    base=AutoModelForCausalLM.from_pretrained(HUGE_BASE,revision=HUGE_BASE_REVISION,dtype=dtype,attn_implementation='eager',device_map=dev)
    path=snapshot_download(repo,revision=revision,allow_patterns=['adapter_config.json','adapter_model.safetensors'])
    model=PeftModel.from_pretrained(base,path,is_trainable=False).eval();model.config.use_cache=False
    return NagiHuge(model,tok,temperature=temperature,max_tokens=max_tokens)
