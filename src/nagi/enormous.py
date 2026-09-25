"""Nagi-ENORMOUS: the single-forward Qwen3.8 27B research readout (draft).

Mirrors ``nagi.huge`` (Nagi-HUGE). Differences from the Gemma path are limited
to the base checkpoint and a guard that the Qwen chat template really emitted
its closed, empty thinking block before the answer letter slot.
"""
from __future__ import annotations
import math
import torch
ENORMOUS_REPO='nagisanzeninz/Nagi-ENORMOUS'
# TODO(enormous-release): pin the 40-char commit sha of the published adapter on
# the Hugging Face Hub before release. load_enormous() refuses to run while None.
ENORMOUS_REVISION=None
ENORMOUS_BASE='Qwen/Qwen3.8-27B'
ENORMOUS_BASE_REVISION='1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0'
ENORMOUS_TRAINED_MAX_TOKENS=768
class NagiEnormous:
    """Typed closed-set decisions, no generation or silent truncation.

    Same contract as NagiHuge. Inputs are capped at 4096 rendered tokens, but the
    adapter was trained on prompts of at most 768 tokens; longer inputs are
    accepted and fall outside the trained range.
    """
    def __init__(self,model,tokenizer,temperature=1.0,max_tokens=4096):
        if not math.isfinite(temperature) or temperature<=0:raise ValueError('temperature must be finite and positive')
        if not isinstance(max_tokens,int) or not 1<=max_tokens<=4096:raise ValueError('max_tokens must be between 1 and 4096')
        self.model=model.eval();self.tok=tokenizer;self.temperature=temperature;self.max_tokens=max_tokens
    def encode(self,state,questions,qid):
        from nagi.render import render_nagi_prompt
        prompt,keys=render_nagi_prompt({'state':state,'questions':questions},qid)
        if not 2<=len(keys)<=26:raise ValueError('Nagi-ENORMOUS supports 2–26 options')
        # Qwen3.x templates read enable_thinking from the template kwargs; with it
        # False the generation prompt ends in an empty "<think>\n\n</think>\n\n".
        chat=self.tok.apply_chat_template([{'role':'user','content':prompt}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        if '<think>' in chat and '</think>' not in chat[chat.rindex('<think>'):]:raise ValueError('Chat template left a thinking block open; enable_thinking=False was not honoured')
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
        # Multimodal Qwen wrappers expose model.language_model; text-only ones do not.
        text=core.model.language_model if hasattr(core.model,'language_model') else core.model
        device=next(self.model.parameters()).device
        for qid,q in questions.items():
            if not isinstance(q,dict) or q.get('type','choice') not in ('choice','score','noul'):raise ValueError('Supported question types: choice, score, noul')
            ids,slots,keys=self.encode(state,questions,qid)
            x=torch.tensor([ids],device=device);mask=torch.ones_like(x)
            last=text(input_ids=x,attention_mask=mask,use_cache=False).last_hidden_state[:,-1]
            z=torch.nn.functional.linear(last,core.get_output_embeddings().weight[torch.tensor(slots,device=device)])
            # Qwen has no final-logit softcap (Gemma does); kept config-driven so it is a no-op here.
            cap=getattr(core.config.get_text_config(),'final_logit_softcapping',None)
            if cap:z=cap*torch.tanh(z/cap)
            p=(z.float()/self.temperature).softmax(-1)[0].cpu().tolist();probs=dict(zip(keys,p))
            answer={'probabilities':probs,'confidence':max(p)};kind=q.get('type','choice')
            if kind=='score':answer['score']=sum(float(k)*v for k,v in probs.items())
            elif kind=='noul':answer['noul']=probs['true']
            else:answer['choice']=keys[max(range(len(p)),key=p.__getitem__)]
            answers[qid]=answer
        return {'answers':answers}
def load_enormous(repo=ENORMOUS_REPO,revision=None,device=None,temperature=1.0,max_tokens=4096):
    """Load pinned Qwen3.8 27B base plus unmerged ENORMOUS adapter.

    Validated path: CUDA BF16, eager attention, unmerged LoRA. BF16 weights are
    ~56 GB, so an 80 GB GPU (H100 / A100-80G) is required. Other devices and
    precisions are not validated.
    """
    if ENORMOUS_REVISION is None:raise RuntimeError('Nagi-ENORMOUS is not released yet: ENORMOUS_REVISION is unpinned. Refusing to load an unpinned adapter.')
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM,AutoTokenizer
    if repo==ENORMOUS_REPO:revision=revision or ENORMOUS_REVISION
    dev=device or ('cuda' if torch.cuda.is_available() else 'cpu')
    dtype=torch.bfloat16 if str(dev).startswith('cuda') else torch.float32
    tok=AutoTokenizer.from_pretrained(ENORMOUS_BASE,revision=ENORMOUS_BASE_REVISION)
    base=AutoModelForCausalLM.from_pretrained(ENORMOUS_BASE,revision=ENORMOUS_BASE_REVISION,dtype=dtype,attn_implementation='eager',device_map=dev)
    path=snapshot_download(repo,revision=revision,allow_patterns=['adapter_config.json','adapter_model.safetensors'])
    model=PeftModel.from_pretrained(base,path,is_trainable=False).eval();model.config.use_cache=False
    return NagiEnormous(model,tok,temperature=temperature,max_tokens=max_tokens)
