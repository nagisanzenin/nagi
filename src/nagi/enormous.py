"""Nagi-ENORMOUS: the single-forward Qwen3.8 27B research readout, plus Nagi-ENORMOUS-Burst.

``system_one(state, questions)`` is unchanged (mode="kcall": one forward per question). ``mode="burst"`` answers
every question (control) in ONE forward; see ``nagi.burst``. ``load_enormous_burst()`` loads the Burst-trained
weights (T-dual step 417) merged in BF16, the path its latency was measured on.

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
ENORMOUS_REVISION='2e03ec38270967a95b66bc68208a5a2e1f6ba3db'
ENORMOUS_BASE='Qwen/Qwen3.8-27B'
ENORMOUS_BASE_REVISION='1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0'
ENORMOUS_TRAINED_MAX_TOKENS=768
BURST_REPO='nagisanzeninz/Nagi-ENORMOUS-Burst'
# Pinned to the published adapter commit at release (owner click). load_enormous_burst() refuses while None.
BURST_REVISION=None
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
        self.burst_trained=False  # True only for weights trained on the Burst format (load_enormous_burst)
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
    def encode_burst(self,state,questions,control_order=None):
        """Burst tokenization + validation in canonical control order; returns ids, positions, letter_ids, slots, order."""
        from nagi.burst import sdk_encode_burst
        return sdk_encode_burst(self,state,questions,control_order)
    def encode_chord(self,state,questions):
        """Deprecated alias of encode_burst (Chord was renamed Burst)."""
        import warnings
        warnings.warn('encode_chord is deprecated; use encode_burst',DeprecationWarning,stacklevel=2)
        return self.encode_burst(state,questions)
    def system_one(self,state,questions,mode='kcall',control_order=None,permutations=None):
        """mode='kcall' (default, unchanged): one forward per question. mode='burst': ONE forward for all questions,
        in canonical control order (control_order, else the state's CONTROLS line, else dict order); permutations=
        'cyclic'|'all' averages over slot orders (experimental, one forward per order). mode='chord' is a deprecated
        alias of 'burst'. Same answer dict per qid in both modes."""
        from nagi.burst import normalize_mode
        mode=normalize_mode(mode)
        if mode=='burst':
            if not self.burst_trained:
                import warnings
                warnings.warn('these weights were not trained for Burst; use load_enormous_burst()',UserWarning,stacklevel=2)
            from nagi.burst import burst_system_one
            return burst_system_one(self,state,questions,control_order=control_order,permutations=permutations)
        if control_order is not None or permutations is not None:raise ValueError('control_order/permutations apply to mode="burst" only')
        return self._kcall(state,questions)
    @torch.inference_mode()
    def _kcall(self,state,questions):
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
def load_enormous_burst(repo=BURST_REPO,revision=None,device=None,temperature=1.0,max_tokens=4096,merge=True):
    """Load Nagi-ENORMOUS-Burst: pinned Qwen3.8 27B base + the Burst-trained adapter (T-dual step 417).

    Validated serving path: CUDA BF16, eager attention, adapter MERGED in place (merge=True), the path the Arena
    latencies were measured on (with the fused Gated-DeltaNet kernels installed). merge=False keeps the LoRA
    unmerged, which can flip near-tie argmaxes relative to the merged path. Needs an 80 GB GPU (~56 GB BF16).
    Refuses to run until BURST_REVISION is pinned to the published adapter commit.
    """
    if BURST_REVISION is None:raise RuntimeError('Nagi-ENORMOUS-Burst is not released yet: BURST_REVISION is unpinned. Refusing to load an unpinned adapter.')
    from huggingface_hub import snapshot_download
    from peft import PeftModel
    from transformers import AutoModelForCausalLM,AutoTokenizer
    if repo==BURST_REPO:revision=revision or BURST_REVISION
    dev=device or ('cuda' if torch.cuda.is_available() else 'cpu')
    dtype=torch.bfloat16 if str(dev).startswith('cuda') else torch.float32
    tok=AutoTokenizer.from_pretrained(ENORMOUS_BASE,revision=ENORMOUS_BASE_REVISION)
    base=AutoModelForCausalLM.from_pretrained(ENORMOUS_BASE,revision=ENORMOUS_BASE_REVISION,dtype=dtype,attn_implementation='eager',device_map=dev)
    path=snapshot_download(repo,revision=revision,allow_patterns=['adapter_config.json','adapter_model.safetensors'])
    model=PeftModel.from_pretrained(base,path,is_trainable=False)
    if merge:model=model.merge_and_unload()
    model.eval();model.config.use_cache=False
    out=NagiEnormous(model,tok,temperature=temperature,max_tokens=max_tokens);out.burst_trained=True
    return out
