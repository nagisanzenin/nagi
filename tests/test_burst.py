"""Burst (one-forward multi-control) readout: prompt parity with the trained format, canonical control order,
permutation averaging, deprecated Chord aliases, and the loader pins. CPU only, tiny fake model, no downloads."""
import hashlib
import sys
import types
import warnings

import pytest
import torch

from nagi import burst, enormous
from nagi.enormous import NagiEnormous
from nagi.render import BURST_BLANK, CHORD_BLANK, render_burst_prompt, render_chord_prompt

STATE = ('RULES: keep the boat level.\ntick 3: water 0.4 m\n\n'
         'CONTROLS (set together each tick): upper_gate = closed | open; lower_gate = closed | open; pump = down | idle | up.')
Q = {'upper_gate': {'type': 'choice', 'instructions': '', 'criteria': {'closed': 'upper gate stays closed this tick',
                                                                     'open': 'upper gate is open this tick'}},
     'lower_gate': {'type': 'choice', 'instructions': '', 'criteria': {'closed': 'lower gate stays closed this tick',
                                                                     'open': 'lower gate is open this tick'}},
     'pump': {'type': 'choice', 'instructions': 'Choose the pump setting.',
              'criteria': {'down': 'pump water out', 'idle': 'leave pump idle', 'up': 'pump water in'}}}
# sha256 of the research renderer's output (nagi-research src/nagi/render.py::render_chord_prompt, the format T-dual was
# trained and evaluated on) for this row in canonical order, and rotated so pump comes first.
GOLDEN_CANONICAL = '5a5409801eaeec994de335bda5559b8b9977a049ad7b8b07038b217c1a65cd38'
GOLDEN_PUMP_FIRST = 'f96961e1d627e0809983e4ef6dcd6a4f2f08bbb0cd807de0aa904acd2e7e8c16'


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def test_prompt_is_byte_identical_to_the_trained_format():
    p, slots = render_burst_prompt({'state': STATE, 'questions': Q}, ['upper_gate', 'lower_gate', 'pump'])
    assert sha(p) == GOLDEN_CANONICAL
    assert slots == [('upper_gate', ['closed', 'open']), ('lower_gate', ['closed', 'open']), ('pump', ['down', 'idle', 'up'])]
    assert sha(render_burst_prompt({'state': STATE, 'questions': Q}, ['pump', 'upper_gate', 'lower_gate'])[0]) == GOLDEN_PUMP_FIRST
    assert p.endswith('ANSWER:\n[1]□\n[2]□\n[3]□') and BURST_BLANK == CHORD_BLANK == '□'


def test_render_chord_prompt_is_a_deprecated_alias():
    with pytest.warns(DeprecationWarning, match='render_burst_prompt'):
        old = render_chord_prompt({'state': STATE, 'questions': Q})
    assert old == render_burst_prompt({'state': STATE, 'questions': Q})


# ----------------------------------------------------------------------------- canonical control order

def test_controls_line_order_is_canonical_regardless_of_dict_order():
    shuffled = {k: Q[k] for k in ('pump', 'lower_gate', 'upper_gate')}
    for qs in (Q, shuffled):
        order, source = burst.canonical_control_order(STATE, qs)
        assert (order, source) == (['upper_gate', 'lower_gate', 'pump'], 'controls_line')


def test_explicit_order_wins_and_is_validated():
    assert burst.canonical_control_order(STATE, Q, ['pump', 'upper_gate', 'lower_gate']) == \
        (['pump', 'upper_gate', 'lower_gate'], 'explicit')
    for bad in (['pump'], ['pump', 'pump', 'upper_gate'], ['pump', 'upper_gate', 'x']):
        with pytest.raises(ValueError, match='permutation'):
            burst.canonical_control_order(STATE, Q, bad)


def test_caller_order_when_no_matching_controls_line():
    assert burst.canonical_control_order('no line here', Q) == (list(Q), 'caller')
    other = STATE.replace('pump = down | idle | up', 'valve = a | b')
    assert burst.canonical_control_order(other, Q) == (list(Q), 'caller')
    assert burst.canonical_control_order({'json': 'state'}, Q) == (list(Q), 'caller')
    assert burst.controls_line_order('CONTROLS (set together each tick): a = x | y; b = z | w') == ['a', 'b']


def test_permutation_orders():
    o = ['a', 'b', 'c']
    assert burst.permutation_orders(o, None) == [o]
    assert burst.permutation_orders(o, 'cyclic') == [['a', 'b', 'c'], ['b', 'c', 'a'], ['c', 'a', 'b']]
    allp = burst.permutation_orders(o, 'all')
    assert len(allp) == 6 and allp[0] == o and len({tuple(p) for p in allp}) == 6
    assert burst.permutation_orders(['a'], 'all') == [['a']]
    with pytest.raises(ValueError):
        burst.permutation_orders(list('abcde'), 'all')
    with pytest.raises(ValueError):
        burst.permutation_orders(o, 'random')


def test_average_and_answer_shape_and_tie_rule():
    runs = [{'q': {'x': 0.6, 'y': 0.4}}, {'q': {'x': 0.4, 'y': 0.6}}]
    avg = burst.average_probabilities(runs)
    assert avg == {'q': {'x': 0.5, 'y': 0.5}}
    a = burst.answer_from_probabilities({'type': 'choice'}, avg['q'])
    assert a['choice'] == 'x' and a['confidence'] == 0.5  # ties -> first option in the question's own order
    assert burst.answer_from_probabilities({'type': 'noul'}, {'false': .3, 'true': .7})['noul'] == .7
    assert burst.answer_from_probabilities({'type': 'score'}, {'0': .5, '1': .5})['score'] == .5
    with pytest.raises(ValueError, match='differ'):
        burst.average_probabilities([{'q': {'x': 1.0}}, {'q': {'y': 1.0}}])


# ----------------------------------------------------------------------------- tokenization + forward (fake model)

class CharTok:
    """One token per character: every Burst boundary check is exercised exactly."""
    def apply_chat_template(self, messages, **kw):
        assert kw['enable_thinking'] is False and kw['add_generation_prompt'] is True
        return '<u>' + messages[0]['content'] + '<a><think>\n\n</think>\n\n'

    def encode(self, text, **kw):
        return [ord(c) for c in text]

    def decode(self, ids):
        return ''.join(chr(i) for i in ids)


class Text(torch.nn.Module):
    def __init__(self, v, h):
        super().__init__()
        self.emb = torch.nn.Embedding(v, h)

    def forward(self, input_ids, attention_mask, use_cache):
        return types.SimpleNamespace(last_hidden_state=self.emb(input_ids).cumsum(1))  # causal: position p sees ids[:p+1]


class TinyLM(torch.nn.Module):
    def __init__(self, v=10000, h=8):
        super().__init__()
        torch.manual_seed(0)
        self.model = Text(v, h)
        self.lm = torch.nn.Linear(h, v, bias=False)
        self.config = types.SimpleNamespace(get_text_config=lambda: types.SimpleNamespace(final_logit_softcapping=None))

    def get_output_embeddings(self):
        return self.lm


def sdk(trained=True):
    n = NagiEnormous(TinyLM(), CharTok(), max_tokens=4096)
    n.burst_trained = trained
    return n


def test_encode_burst_positions_and_limits():
    n = sdk()
    enc = n.encode_burst(STATE, Q)
    assert enc['order'] == ['upper_gate', 'lower_gate', 'pump'] and enc['order_source'] == 'controls_line'
    assert enc['blank_id'] == ord(BURST_BLANK)
    assert [enc['ids'][p + 1] for p in enc['positions']] == [ord(BURST_BLANK)] * 3
    assert [enc['chat'][p] for p in enc['positions']] == [']'] * 3
    assert enc['letter_ids'] == [[65, 66], [65, 66], [65, 66, 67]]
    n.max_tokens = 10
    with pytest.raises(ValueError, match='No truncation'):
        n.encode_burst(STATE, Q)
    with pytest.raises(ValueError, match='must not occur'):
        sdk().encode_burst('state with a □ inside', Q)


def test_burst_one_forward_answers_in_caller_order():
    n = sdk()
    shuffled = {k: Q[k] for k in ('pump', 'lower_gate', 'upper_gate')}
    a = n.system_one(STATE, Q, mode='burst')
    b = n.system_one(STATE, shuffled, mode='burst')
    assert list(a['answers']) == list(Q) and list(b['answers']) == list(shuffled)
    assert a['burst'] == {'order': ['upper_gate', 'lower_gate', 'pump'], 'order_source': 'controls_line', 'forwards': 1,
                          'permutations': None}
    for qid in Q:  # canonical order: dict order does not change the prompt, so answers are identical
        assert a['answers'][qid] == b['answers'][qid]
        assert abs(sum(a['answers'][qid]['probabilities'].values()) - 1) < 1e-6
        assert a['answers'][qid]['choice'] in Q[qid]['criteria']


def test_explicit_order_changes_the_prompt_and_permutation_average_removes_it():
    n = sdk()
    x = n.system_one(STATE, Q, mode='burst', control_order=['pump', 'upper_gate', 'lower_gate'])
    y = n.system_one(STATE, Q, mode='burst')
    assert x['burst']['order_source'] == 'explicit'
    assert any(x['answers'][q]['probabilities'] != y['answers'][q]['probabilities'] for q in Q)
    ax = n.system_one(STATE, Q, mode='burst', control_order=['pump', 'upper_gate', 'lower_gate'], permutations='all')
    ay = n.system_one(STATE, Q, mode='burst', permutations='all')
    assert ax['burst']['forwards'] == ay['burst']['forwards'] == 6
    for q in Q:
        for k in Q[q]['criteria']:
            assert ax['answers'][q]['probabilities'][k] == pytest.approx(ay['answers'][q]['probabilities'][k], abs=1e-6)
    assert n.system_one(STATE, Q, mode='burst', permutations='cyclic')['burst']['forwards'] == 3


def test_chord_mode_is_a_deprecated_alias():
    n = sdk()
    with pytest.warns(DeprecationWarning, match='burst'):
        old = n.system_one(STATE, Q, mode='chord')
    assert old == n.system_one(STATE, Q, mode='burst')
    with pytest.warns(DeprecationWarning):
        assert n.encode_chord(STATE, Q)['ids'] == n.encode_burst(STATE, Q)['ids']
    with pytest.warns(DeprecationWarning):
        burst.chord_slot_positions([1, 9, 2, 9], 9, 2)


def test_untrained_weights_warn_and_bad_modes_raise():
    with pytest.warns(UserWarning, match='not trained for Burst'):
        sdk(trained=False).system_one(STATE, Q, mode='burst')
    with pytest.raises(ValueError, match="mode must be"):
        sdk().system_one(STATE, Q, mode='joint')
    with pytest.raises(ValueError, match='mode="burst" only'):
        sdk().system_one(STATE, Q, control_order=list(Q))


def test_default_mode_is_still_kcall():
    n = sdk()
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        with pytest.raises(ValueError):  # K-call path uses the single-question renderer; the fake tokenizer has no
            n.system_one(STATE, {'q': {'type': 'choice', 'criteria': {'a': 'a'}}})  # 1-option question -> refused
    out = n.system_one(STATE, {'pump': Q['pump']})
    assert set(out) == {'answers'} and set(out['answers']['pump']['probabilities']) == {'down', 'idle', 'up'}


# ----------------------------------------------------------------------------- loader pins

def _fake_stack(monkeypatch, calls):
    class Model:
        config = types.SimpleNamespace(use_cache=True)

        def eval(self):
            return self

        def merge_and_unload(self):
            calls['merged'] = True
            return self

    class Factory:
        @staticmethod
        def from_pretrained(repo, **kwargs):
            calls['base'] = (repo, kwargs)
            return Model()

    class Tokenizer:
        @staticmethod
        def from_pretrained(repo, **kwargs):
            calls['tokenizer'] = (repo, kwargs)
            return object()

    class Peft:
        @staticmethod
        def from_pretrained(base, path, **kwargs):
            calls['adapter'] = (path, kwargs)
            return base

    hub = types.ModuleType('huggingface_hub')
    hub.snapshot_download = lambda repo, **kw: calls.__setitem__('snapshot', (repo, kw)) or '/adapter'
    tf = types.ModuleType('transformers')
    tf.AutoModelForCausalLM, tf.AutoTokenizer = Factory, Tokenizer
    peft = types.ModuleType('peft')
    peft.PeftModel = Peft
    for name, m in [('huggingface_hub', hub), ('transformers', tf), ('peft', peft)]:
        monkeypatch.setitem(sys.modules, name, m)


def test_burst_loader_refuses_while_unpinned(monkeypatch):
    calls = {}
    _fake_stack(monkeypatch, calls)
    monkeypatch.setattr(enormous, 'BURST_REVISION', None)
    with pytest.raises(RuntimeError, match='unpinned'):
        enormous.load_enormous_burst(device='cuda')
    assert calls == {}


def test_burst_loader_exact_path(monkeypatch):
    calls = {}
    _fake_stack(monkeypatch, calls)
    monkeypatch.setattr(enormous, 'BURST_REVISION', '1' * 40)
    out = enormous.load_enormous_burst(device='cuda')
    assert enormous.BURST_REPO == 'nagisanzeninz/Nagi-ENORMOUS-Burst'
    assert calls['snapshot'] == (enormous.BURST_REPO, {'revision': '1' * 40,
                                                      'allow_patterns': ['adapter_config.json', 'adapter_model.safetensors']})
    assert calls['base'][0] == calls['tokenizer'][0] == 'Qwen/Qwen3.8-27B'
    assert calls['base'][1]['revision'] == calls['tokenizer'][1]['revision'] == enormous.ENORMOUS_BASE_REVISION
    assert calls['base'][1]['attn_implementation'] == 'eager' and str(calls['base'][1]['dtype']) == 'torch.bfloat16'
    assert calls['merged'] is True and out.burst_trained is True and not out.model.config.use_cache
    calls.clear()
    _fake_stack(monkeypatch, calls)
    enormous.load_enormous_burst(device='cuda', merge=False)
    assert 'merged' not in calls
