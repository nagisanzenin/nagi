"""Keep copy-paste examples self-contained without downloading weights in CI."""
import json
import re
from pathlib import Path

import nagi
import pytest

ROOT = Path(__file__).resolve().parents[1]


class ExampleModel:
    def system_one(self, state, questions):
        json.dumps(state)
        assert state and questions
        answers = {}
        for qid, q in questions.items():
            assert q['instructions']
            kind = q['type']
            assert kind in {'choice', 'score', 'noul'}
            if kind == 'choice':
                assert isinstance(q['criteria'], dict) and len(q['criteria']) >= 2
                keys = list(q['criteria'])
            elif kind == 'score':
                assert isinstance(q['criteria'], list) and len(q['criteria']) >= 2
                keys = [str(i) for i in range(len(q['criteria']))]
            else:
                keys = ['false', 'true']
            answer = {'probabilities': {k: 1 / len(keys) for k in keys}, 'confidence': 1 / len(keys)}
            answer[kind] = keys[0] if kind == 'choice' else 0.5
            answers[qid] = answer
        return {'answers': answers}


@pytest.mark.parametrize('relative', ['README.md', 'docs/INSTALL.md', 'docs/RECIPES.md'])
def test_python_blocks_are_self_contained(relative, monkeypatch):
    monkeypatch.setattr(nagi, 'load_smol', lambda **kwargs: ExampleModel())
    monkeypatch.setattr(nagi, 'load_big', lambda **kwargs: ExampleModel())
    blocks = re.findall(r'```python\n(.*?)```', (ROOT / relative).read_text(), re.S)
    assert blocks
    for block in blocks:
        # A fresh namespace catches examples relying on variables from another block.
        exec(compile(block, relative, 'exec'), {'__name__': '__documented_example__'})
