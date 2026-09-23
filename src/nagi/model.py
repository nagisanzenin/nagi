from __future__ import annotations

import torch
import torch.nn as nn
from transformers import AutoModel, AutoTokenizer

QTYPE_TO_ID = {"choice": 0, "score": 1, "noul": 2}


class OptionTower(nn.Module):
    def __init__(self, vocab_size: int, d: int, n_layers: int = 2, max_len: int = 64):
        super().__init__()
        self.max_len = max_len
        self.emb = nn.Embedding(vocab_size, d)
        self.pos = nn.Embedding(max_len, d)
        layer = nn.TransformerEncoderLayer(
            d_model=d,
            nhead=8 if d % 8 == 0 else 4,
            dim_feedforward=4 * d,
            dropout=0.1,
            batch_first=True,
            activation="gelu",
            norm_first=True,
        )
        self.enc = nn.TransformerEncoder(layer, num_layers=n_layers)
        self.norm = nn.LayerNorm(d)

    def forward(self, ids: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        B, K, L = ids.shape
        pos = torch.arange(L, device=ids.device).clamp_max(self.max_len - 1)
        x = self.emb(ids) + self.pos(pos)[None, None, :, :]
        x = x.view(B * K, L, -1)
        m = mask.view(B * K, L).bool()
        h = self.enc(x, src_key_padding_mask=~m)
        h = (h * m.unsqueeze(-1)).sum(1) / m.sum(1, keepdim=True).clamp_min(1)
        return self.norm(h).view(B, K, -1)


class ScoreHead(nn.Module):
    def __init__(self, d: int, use_cross_attn: bool = False):
        super().__init__()
        self.use_cross_attn = use_cross_attn
        n_head = 8 if d % 8 == 0 else 4
        self.attn = nn.MultiheadAttention(d, num_heads=n_head, batch_first=True) if use_cross_attn else None
        self.mlp = nn.Sequential(nn.Linear(4 * d, 2 * d), nn.GELU(), nn.Dropout(0.1), nn.Linear(2 * d, 1))
        self.qtype_emb = nn.Embedding(3, d)

    def forward(self, h_pool, H, state_mask, e, qtype):
        B, K, d = e.shape
        hp = h_pool + self.qtype_emb(qtype)
        hp_e = hp.unsqueeze(1).expand(-1, K, -1)
        feats = torch.cat([hp_e, e, (hp_e - e).abs(), hp_e * e], dim=-1)
        s = self.mlp(feats).squeeze(-1)
        if self.attn is not None:
            q = e.reshape(B * K, 1, d)
            kv = H.unsqueeze(1).expand(-1, K, -1, -1).reshape(B * K, H.size(1), d)
            key_m = ~state_mask.unsqueeze(1).expand(-1, K, -1).reshape(B * K, -1).bool()
            ctx, _ = self.attn(q, kv, kv, key_padding_mask=key_m)
            ctx = ctx.reshape(B, K, d)
            s = s + (ctx * e).sum(-1) / (d**0.5)
        return s


class NagiM2P(nn.Module):
    def __init__(
        self,
        state_encoder: str = "answerdotai/ModernBERT-large",
        option_layers: int = 2,
        option_max_len: int = 64,
        state_max_len: int = 512,
        use_cross_attn: bool = False,
    ):
        super().__init__()
        self.state_max_len = state_max_len
        self.option_max_len = option_max_len
        self.encoder = AutoModel.from_pretrained(state_encoder)
        d = self.encoder.config.hidden_size
        self.d = d
        self.opt = OptionTower(self.encoder.config.vocab_size, d, option_layers, option_max_len)
        self.head = ScoreHead(d, use_cross_attn)
        self.tokenizer = AutoTokenizer.from_pretrained(state_encoder)

    def forward(self, input_ids, attention_mask, opt_ids, opt_mask, qtype):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        H = out.last_hidden_state
        m = attention_mask.unsqueeze(-1)
        h = (H * m).sum(1) / m.sum(1).clamp_min(1)
        e = self.opt(opt_ids, opt_mask)
        return self.head(h, H, attention_mask, e, qtype)


def build_model(cfg: dict) -> NagiM2P:
    m = cfg.get("model", {})
    return NagiM2P(
        state_encoder=m.get("state_encoder", "answerdotai/ModernBERT-large"),
        option_layers=m.get("option_layers", 2),
        option_max_len=m.get("option_max_len", 64),
        state_max_len=m.get("state_max_len", 512),
        use_cross_attn=m.get("use_cross_attn", False),
    )
