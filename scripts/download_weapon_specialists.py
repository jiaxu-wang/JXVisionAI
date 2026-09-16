#!/usr/bin/env python3
"""下载枪支 / 刀具 YOLO 检测权重并登记为专模。

枪支：Subh775/Firearm_Detection_Yolov8n（单类 Gun，公开 mAP@0.5≈89%）
刀具：Subh775/Threat-Detection-YOLOv8n（四类里只启用 Knife，关闭爆炸物）

权重不入 Git。国内可：HF_ENDPOINT=https://hf-mirror.com python3 scripts/download_weapon_specialists.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GUN_REPO = "Subh775/Firearm_Detection_Yolov8n"
GUN_FILE = "weights/best.pt"
KNIFE_REPO = "Subh775/Threat-Detection-YOLOv8n"
KNIFE_FILE = "weights/best.pt"

UA = "JXVisionAI-weapon-download/1.0"


def _hf_bases() -> list[str]:
    import os

    primary = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    mirrors = [primary, "https://hf-mirror.com", "https://huggingface.co"]
    out: list[str] = []
    for item in mirrors:
        if item and item not in out:
            out.append(item)
    return out


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    print(f"GET {url}")
    with urllib.request.urlopen(req, timeout=120) as resp, open(part, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    size = part.stat().st_size
    if size < 100_000:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"下载过小，可能不是权重: {url} ({size} B)")
    part.replace(dest)
    print(f"  -> {dest} ({dest.stat().st_size / 1024 / 1024:.2f} MB)")


def _class_index(classes: list[str], *needles: str) -> int | None:
    lower = [c.strip().lower() for c in classes]
    for n in needles:
        n = n.lower()
        for i, c in enumerate(lower):
            if c == n or n in c:
                return i
    return None


def _inspect(path: Path) -> list[str]:
    from visionai.config.specialists import inspect_yolo_weights

    info = inspect_yolo_weights(path)
    if not info.get("success"):
        raise RuntimeError(info.get("message") or "无法读取权重")
    classes = [str(x) for x in (info.get("classes") or [])]
    print(f"  classes={classes}")
    return classes


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并登记枪支/刀具专模")
    parser.add_argument("--force", action="store_true", help="已存在权重也重新下载")
    args = parser.parse_args()

    from visionai.config.settings import PROJECT_ROOT
    from visionai.config.specialists import deploy_specialist

    repo = Path(PROJECT_ROOT)
    now = time.time()
    raw_dir = repo / "models" / "specialists" / "_weapon_cache"
    gun_raw = raw_dir / "firearm_yolov8n.pt"
    knife_raw = raw_dir / "threat_yolov8n.pt"

    def fetch(rel_repo: str, rel_file: str, dest: Path) -> None:
        if dest.is_file() and not args.force:
            print(f"skip {dest}")
            return
        last_err: Exception | None = None
        for base in _hf_bases():
            url = f"{base}/{rel_repo}/resolve/main/{rel_file}"
            try:
                _download(url, dest)
                return
            except Exception as ex:  # noqa: BLE001
                last_err = ex
                print(f"  failed {base}: {ex}")
        raise RuntimeError(f"下载失败 {rel_repo}/{rel_file}: {last_err}")

    fetch(GUN_REPO, GUN_FILE, gun_raw)
    fetch(KNIFE_REPO, KNIFE_FILE, knife_raw)

    gun_classes = _inspect(gun_raw)
    knife_classes = _inspect(knife_raw)
    gun_id = _class_index(gun_classes, "gun", "firearm", "pistol", "rifle")
    if gun_id is None:
        gun_id = 0
    knife_id = _class_index(knife_classes, "knife", "blade", "dagger")
    if knife_id is None:
        raise RuntimeError(f"威胁模型中未找到 knife 类: {knife_classes}")

    gun = deploy_specialist(
        repo,
        weights_path=gun_raw,
        key="gun",
        kind="scene",
        name_zh="枪支检测",
        name_en="gun",
        classes=gun_classes,
        conf=0.45,
        score_threshold=0.45,
        min_duration_sec=1.0,
        class_ids=[gun_id],
        positive_class_ids=[gun_id],
        needs_persons=False,
        origin="imported",
        backup=True,
    )
    knife = deploy_specialist(
        repo,
        weights_path=knife_raw,
        key="knife",
        kind="scene",
        name_zh="刀具检测",
        name_en="knife",
        classes=knife_classes,
        conf=0.50,
        score_threshold=0.50,
        min_duration_sec=1.5,
        class_ids=[knife_id],
        positive_class_ids=[knife_id],
        needs_persons=False,
        origin="imported",
        backup=True,
    )
    if not gun.get("success"):
        print(gun.get("message"), file=sys.stderr)
        return 1
    if not knife.get("success"):
        print(knife.get("message"), file=sys.stderr)
        return 1

    source = {
        "gun": {
            "repo": GUN_REPO,
            "file": GUN_FILE,
            "url": f"https://huggingface.co/{GUN_REPO}",
            "class_id": gun_id,
            "note": "单类枪支检测；爆炸物未启用",
        },
        "knife": {
            "repo": KNIFE_REPO,
            "file": KNIFE_FILE,
            "url": f"https://huggingface.co/{KNIFE_REPO}",
            "class_id": knife_id,
            "note": "四类威胁模型仅启用 Knife，忽略 Gun/Explosive/Grenade",
        },
        "updated_at": now,
    }
    (raw_dir / "SOURCE.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        from visionai.core.behaviors.registry import reload_plugins

        reload_plugins()
    except Exception as ex:  # noqa: BLE001
        print(f"插件热加载跳过（worker 下周期会加载）: {ex}")
    print(gun["message"])
    print(knife["message"])
    print("检测配置中勾选「枪支检测」「刀具检测」后保存。worker 下一周期会加载新专模。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
