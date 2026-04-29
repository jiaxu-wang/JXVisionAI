#!/usr/bin/env python3
"""从 Hugging Face 导出吸烟二分类 ONNX，供 VisionAI 行为层使用。

默认模型: dima806/smoker_image_classification (ViT，类别 0=notsmoking, 1=smoking)。

依赖（建议在项目 venv 中）:
  ./env/bin/pip install torch transformers onnx

用法:
  ./env/bin/python scripts/export_smoking_onnx.py -o models/smoking_vit.onnx

下载慢或一直 0%：多为拉取 ~343MB 权重受阻。任选其一（仅当前终端有效）:

  1) HTTP/HTTPS 代理（Clash 须开 Allow LAN；建议在 VM 内 curl 测通代理）:
     export http_proxy=http://192.168.2.128:7897
     export https_proxy=http://192.168.2.128:7897
     export HTTP_PROXY="$http_proxy" HTTPS_PROXY="$https_proxy"

  2) Hugging Face 镜像:
     export HF_ENDPOINT=https://hf-mirror.com

  若代理是 SOCKS5，需用支持 SOCKS 的变量/工具，或把 Clash 设为「系统代理」后在本机终端执行。

  Python 进度条一直 0%：可改用 curl 只下权重（走 -x 代理），再离线导出:
    mkdir -p models/hf_smoking && cd models/hf_smoking
    curl -x http://192.168.2.128:7897 -L -o config.json \\
      https://huggingface.co/dima806/smoker_image_classification/resolve/main/config.json
    curl -x http://192.168.2.128:7897 -L -o model.safetensors \\
      https://huggingface.co/dima806/smoker_image_classification/resolve/main/model.safetensors
    cd ../..
    ./env/bin/python scripts/export_smoking_onnx.py --local-dir models/hf_smoking -o models/smoking_vit.onnx

导出后在 config.ini 的 [visionai] 中配置:
  smoking_model_path = （本脚本输出的路径）
  smoking_preprocess = vit_hf
  smoking_positive_class_index = 1
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    # hf_transfer 等加速可能不走 HTTP_PROXY，在 VM + 局域网代理场景易表现为一直 0%
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

    parser = argparse.ArgumentParser(description="导出吸烟分类 ONNX")
    parser.add_argument(
        "--model-id",
        default="dima806/smoker_image_classification",
        help="Hugging Face 模型 ID（与 --local-dir 二选一）",
    )
    parser.add_argument(
        "--local-dir",
        default="",
        help="已含 config.json + model.safetensors 的本地目录，不访问 Hub（推荐下载卡住时使用）",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="models/smoking_vit.onnx",
        help="输出 .onnx 路径",
    )
    parser.add_argument("--opset", type=int, default=14)
    args = parser.parse_args()

    try:
        import torch
        import torch.nn as nn
        from transformers import AutoModelForImageClassification
    except ImportError as e:
        print(
            "缺少依赖，请执行: ./env/bin/pip install torch transformers",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    local = (args.local_dir or "").strip()
    if local:
        src = Path(local).expanduser().resolve()
        if not src.is_dir():
            print(f"目录不存在: {src}", file=sys.stderr)
            raise SystemExit(1)
        cfg = src / "config.json"
        weights = src / "model.safetensors"
        if not weights.is_file():
            alt = src / "pytorch_model.bin"
            weights = alt if alt.is_file() else weights
        if not cfg.is_file() or not weights.is_file():
            print(
                f"本地目录需同时包含 config.json 与 model.safetensors（或 pytorch_model.bin）: {src}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(f"从本地加载（不访问 Hugging Face）: {src}")
        model = AutoModelForImageClassification.from_pretrained(
            str(src), local_files_only=True
        )
    else:
        print(f"正在从 Hugging Face 加载: {args.model_id} …")
        model = AutoModelForImageClassification.from_pretrained(args.model_id)
    model.eval()

    class LogitsWrapper(nn.Module):
        def __init__(self, m: nn.Module) -> None:
            super().__init__()
            self.m = m

        def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
            return self.m(pixel_values).logits

    wrapped = LogitsWrapper(model)
    dummy = torch.randn(1, 3, 224, 224, dtype=torch.float32)

    # PyTorch 2.9+ 默认 dynamo=True，会拉 onnxscript；行为层导出用传统 TorchScript 即可
    torch.onnx.export(
        wrapped,
        dummy,
        str(out),
        input_names=["input"],
        output_names=["logits"],
        opset_version=args.opset,
        dynamo=False,
        do_constant_folding=True,
    )

    print(f"已导出 ONNX: {out}")
    print("")
    print("请在 config.ini 的 [visionai] 中增加或修改:")
    print(f"  smoking_model_path = {out}")
    print("  smoking_preprocess = vit_hf")
    print("  smoking_positive_class_index = 1")


if __name__ == "__main__":
    main()
