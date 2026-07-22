#!/usr/bin/env python3
"""从 redis-data/_emergency_export/*.json 恢复 visionai Redis 键。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import redis  # noqa: E402
from visionai.config import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "export_json",
        nargs="?",
        help="导出 JSON；默认取 redis-data/_emergency_export 下最新文件",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=16379)
    args = ap.parse_args()

    if args.export_json:
        path = Path(args.export_json)
    else:
        d = ROOT / "redis-data" / "_emergency_export"
        files = sorted(d.glob("visionai_redis_*.json"))
        if not files:
            print("未找到导出文件", file=sys.stderr)
            return 1
        path = files[-1]

    data = json.loads(path.read_text(encoding="utf-8"))
    keys = data.get("keys") or {}
    r = redis.Redis(
        host=args.host,
        port=args.port,
        password=settings.REDIS_PASSWORD,
        db=settings.REDIS_DB,
        decode_responses=True,
        lib_name=None,
        lib_version=None,
    )
    r.ping()
    try:
        r.config_set("stop-writes-on-bgsave-error", "no")
    except Exception:
        pass

    for k, item in keys.items():
        t = item.get("type")
        val = item.get("value")
        r.delete(k)
        if t == "string":
            r.set(k, val)
        elif t == "list":
            if val:
                r.rpush(k, *val)
        elif t == "hash":
            if val:
                r.hset(k, mapping=val)
        elif t == "set":
            if val:
                r.sadd(k, *val)
        elif t == "zset":
            for member, score in val or []:
                r.zadd(k, {member: score})
        else:
            print(f"skip unsupported {k} type={t}")
            continue
        print(f"restored {k} ({t})")

    print(f"done from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
