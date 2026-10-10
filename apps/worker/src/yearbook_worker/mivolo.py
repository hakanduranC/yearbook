"""MiVOLO v2 age estimation (face crop, optional body crop) as a plain timm VOLO.

The published checkpoint `iitolstykh/mivolo_v2` (Apache-2.0 weights) is `volo_d1_384` with a
two-branch stem (face / body), a cross-attention block that fuses the two 192-d streams into one
384-d token map, and a 3-way head (gender logits, normalised age). The hub repo only ships the
weights; its `auto_map` points at the `mivolo` pip package. This file re-implements the two custom
modules on top of timm so no remote code is executed and no extra package is pulled in. Architecture
follows github.com/WildChlamydia/MiVOLO (mivolo/model/*.py).

Age is `age = out[:, 2] * (max_age - min_age) + avg_age` with the constants from the hub config.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class CrossBottleneckAttn(nn.Module):
    """Face tokens attend to body tokens and vice versa; concat → LayerNorm → conv MLP."""

    def __init__(self, dim: int, feat_size: tuple[int, int], num_heads: int = 1) -> None:
        super().__init__()
        from timm.layers.bottleneck_attn import PosEmbedRel
        from timm.layers.mlp import Mlp

        self.num_heads = num_heads
        self.dim_head = dim // num_heads
        self.scale = self.dim_head**-0.5
        inner = 3 * dim
        self.qkv_f = nn.Conv2d(dim, inner, 1, bias=False)
        self.qkv_p = nn.Conv2d(dim, inner, 1, bias=False)
        self.pos_embed = PosEmbedRel(feat_size, dim_head=self.dim_head, scale=self.scale)
        self.norm = nn.LayerNorm([dim * 2, *feat_size])
        self.mlp = Mlp(dim * 2, hidden_features=dim * 4, out_features=dim, use_conv=True)

    def _qkv(self, x: torch.Tensor, conv: nn.Conv2d) -> tuple[torch.Tensor, ...]:
        b = x.shape[0]
        q, k, v = torch.split(conv(x), [self.dim_head] * 3 * self.num_heads, dim=1)[:3]
        q = q.reshape(b * self.num_heads, self.dim_head, -1).transpose(-1, -2)
        k = k.reshape(b * self.num_heads, self.dim_head, -1)
        v = v.reshape(b * self.num_heads, self.dim_head, -1).transpose(-1, -2)
        return q, k, v

    def _attend(
        self, q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, b: int, h: int, w: int
    ) -> torch.Tensor:
        attn = (q @ k) * self.scale + self.pos_embed(q)
        attn = attn.softmax(dim=-1)
        return (attn @ v).transpose(-1, -2).reshape(b, self.dim_head * self.num_heads, h, w)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, h, w = x.shape
        half = c // 2
        q_f, k_f, v_f = self._qkv(x[:, :half], self.qkv_f)
        q_p, k_p, v_p = self._qkv(x[:, half:], self.qkv_p)
        out_f = self._attend(q_f, k_p, v_p, b, h, w)
        out_p = self._attend(q_p, k_f, v_f, b, h, w)
        return self.mlp(self.norm(torch.cat((out_f, out_p), dim=1)))


def _stem(hidden: int = 64, stride: int = 2) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(3, hidden, 7, stride, 3, bias=False),
        nn.BatchNorm2d(hidden),
        nn.ReLU(inplace=True),
        nn.Conv2d(hidden, hidden, 3, 1, 1, bias=False),
        nn.BatchNorm2d(hidden),
        nn.ReLU(inplace=True),
        nn.Conv2d(hidden, hidden, 3, 1, 1, bias=False),
        nn.BatchNorm2d(hidden),
        nn.ReLU(inplace=True),
    )


class TwoStreamPatchEmbed(nn.Module):
    """Face (channels 0..2) and body (3..5) stems, 192-d each, fused by cross attention."""

    def __init__(self, img_size: int = 384, embed_dim: int = 384, patch: int = 8) -> None:
        super().__init__()
        stride = 2
        self.conv1, self.conv2 = _stem(stride=stride), _stem(stride=stride)
        k = patch // stride
        self.proj1 = nn.Conv2d(64, embed_dim // 2, k, k)
        self.proj2 = nn.Conv2d(64, embed_dim // 2, k, k)
        feat = img_size // stride // k
        self.map = CrossBottleneckAttn(embed_dim // 2, (feat, feat), num_heads=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        face = self.proj1(self.conv1(x[:, :3]))
        body = self.proj2(self.conv2(x[:, 3:]))
        return self.map(torch.cat([face, body], dim=1))


@dataclass(slots=True)
class AgeConfig:
    input_size: int = 384
    min_age: float = 0.0
    max_age: float = 122.0
    avg_age: float = 61.0


class MiVOLO:
    """Loaded model plus pre/post-processing. Call `predict_ages`."""

    def __init__(self, model: nn.Module, config: AgeConfig, name: str) -> None:
        self.model = model
        self.config = config
        self.name = name
        self._mean = torch.tensor(IMAGENET_MEAN).view(1, 3, 1, 1)
        self._std = torch.tensor(IMAGENET_STD).view(1, 3, 1, 1)

    @classmethod
    def from_hub(cls, repo: str) -> MiVOLO:
        """Download `config.json` + `model.safetensors` (HF cache) and build the network."""
        import timm
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file

        cfg_path = Path(hf_hub_download(repo, "config.json"))
        raw = json.loads(cfg_path.read_text())
        config = AgeConfig(
            input_size=int(raw.get("input_size", 384)),
            min_age=float(raw.get("min_age", 0)),
            max_age=float(raw.get("max_age", 122)),
            avg_age=float(raw.get("avg_age", 61)),
        )
        variant = str(raw.get("model_name", "mivolo_d1_384")).replace("mivolo_", "volo_")
        model = timm.create_model(variant, pretrained=False, num_classes=int(raw["num_classes"]))
        model.patch_embed = TwoStreamPatchEmbed(config.input_size, int(model.pos_embed.shape[-1]))
        state = load_file(hf_hub_download(repo, "model.safetensors"))
        state = {k.removeprefix("mivolo.model."): v.float() for k, v in state.items()}
        model.load_state_dict(state, strict=True)
        model.eval()
        return cls(model, config, repo)

    # -- pre-processing (letterbox to a black square, ImageNet normalisation) ------------

    def _prep(self, crop: np.ndarray | None) -> torch.Tensor:
        size = self.config.input_size
        if crop is None:
            return (torch.zeros(1, 3, size, size) - self._mean) / self._std
        canvas = letterbox(crop, size)
        t = torch.from_numpy(np.ascontiguousarray(canvas.transpose(2, 0, 1))).float() / 255.0
        return (t.unsqueeze(0) - self._mean) / self._std

    @torch.inference_mode()
    def predict_ages(
        self, faces: list[np.ndarray | None], bodies: list[np.ndarray | None] | None = None
    ) -> np.ndarray:
        """Ages in years, one per face. Crops are RGB uint8 HxWx3; `None` means missing."""
        if not faces:
            return np.zeros(0, dtype=np.float32)
        bodies = bodies or [None] * len(faces)
        pairs = zip(faces, bodies, strict=True)
        batch = torch.cat([torch.cat([self._prep(f), self._prep(b)], dim=1) for f, b in pairs])
        out = self.model(batch)
        ages = out[:, 2] * (self.config.max_age - self.config.min_age) + self.config.avg_age
        return ages.clamp(0, 110).cpu().numpy().astype(np.float32)


def letterbox(im: np.ndarray, size: int) -> np.ndarray:
    """Resize keeping the aspect ratio and pad with black to a `size` square (MiVOLO's input)."""
    import cv2

    h, w = im.shape[:2]
    r = min(size / h, size / w)
    nw, nh = max(1, round(w * r)), max(1, round(h * r))
    resized = cv2.resize(im, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else im
    dw, dh = (size - nw) / 2, (size - nh) / 2
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    return cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(0, 0, 0)
    )
