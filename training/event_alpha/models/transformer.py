"""Multi-task Financial Transformer: encoder([CLS]) + market-feature MLP → {3-class, 1d/3d/5d alpha}.

encoder 는 로컬 경로(pretrained_dir)에서만 로드한다 (offline-first, HF id 하드코딩 없음).
출력은 alpha 추정치뿐이며 주문/수량/거래소 개념은 포함하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn


class EventAlphaModel(nn.Module):
    def __init__(
        self,
        pretrained_dir: str | Path,
        n_market: int,
        n_horizons: int,
        market_hidden: int = 64,
        dropout: float = 0.1,
        n_classes: int = 3,
    ) -> None:
        super().__init__()
        from transformers import AutoModel

        self.encoder = AutoModel.from_pretrained(str(pretrained_dir), local_files_only=True)
        h = self.encoder.config.hidden_size
        self.market = nn.Sequential(
            nn.Linear(n_market, market_hidden), nn.GELU(), nn.Dropout(dropout)
        )
        self.trunk = nn.Sequential(
            nn.Linear(h + market_hidden, 256), nn.GELU(), nn.Dropout(dropout)
        )
        self.cls_head = nn.Linear(256, n_classes)
        self.reg_head = nn.Linear(256, n_horizons)

    def forward(
        self, input_ids: torch.Tensor, market: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        attn = (input_ids != 0).long()
        out = self.encoder(input_ids=input_ids, attention_mask=attn)
        cls = out.last_hidden_state[:, 0]
        z = self.trunk(torch.cat([cls, self.market(market)], dim=-1))
        return self.cls_head(z), self.reg_head(z)

    def param_groups(self, lr: float, head_lr: float, wd: float) -> list[dict]:
        enc = [p for p in self.encoder.parameters() if p.requires_grad]
        head = [p for n, p in self.named_parameters() if not n.startswith("encoder.")]
        return [
            {"params": enc, "lr": lr, "weight_decay": wd, "base_lr": lr},
            {"params": head, "lr": head_lr, "weight_decay": 0.0, "base_lr": head_lr},
        ]
