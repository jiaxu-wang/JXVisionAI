"""
人脸库：人员元数据与 512 维特征存 Redis，登记照存 MinIO/S3。

Redis Hash：``visionai/face_library:persons``（field = person_id）。
对象键：``visionai/face_library/{person_id}/photo.jpg``。

进程内维护归一化后的 embedding 列表，供 1:N 余弦相似度检索。
若 Redis 为空且本地仍有旧版 ``face_library/`` 目录，启动时会尝试迁移。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from visionai.config.settings import FACE_LIBRARY_DIR, PROJECT_ROOT
from visionai.core import face_engine
from visionai.core.object_storage import get_object_storage
from visionai.core.redis_manager import redis_manager

logger = logging.getLogger(__name__)

# 陌生人告警的稳定 person_id；调度证件号 / 下游协议不允许空值。
UNKNOWN_PERSON_ID = "unknown"
_RESERVED_IDENTITY = frozenset({"unknown", "stranger", "陌生人", ""})

_lock = threading.Lock()
_index: Dict[str, Dict[str, Any]] = {}
_embeddings: List[Tuple[str, np.ndarray]] = []


def _legacy_lib_root() -> str:
    path = (FACE_LIBRARY_DIR or "").strip()
    if not path:
        path = os.path.join(PROJECT_ROOT, "face_library")
    return os.path.abspath(path)


def _legacy_person_dir(person_id: str) -> str:
    return os.path.join(_legacy_lib_root(), "persons", person_id)


def _new_person_id() -> str:
    return "p_" + uuid.uuid4().hex[:12]


def normalize_identity_id(raw: Any) -> str:
    """录入用的身份ID（工号/证件号），同时作为 Redis person_id。"""
    return re.sub(r"\s+", "", str(raw or "")).strip()


def resolve_person_id(raw: Any) -> str:
    """告警协议 person_id：空值一律落成 unknown。"""
    s = str(raw or "").strip()
    return s if s else UNKNOWN_PERSON_ID


def validate_identity_id(raw: Any) -> str:
    pid = normalize_identity_id(raw)
    if not pid:
        raise ValueError("请填写身份ID")
    if len(pid) > 64:
        raise ValueError("身份ID 最长 64 个字符")
    if pid.lower() in _RESERVED_IDENTITY or pid in _RESERVED_IDENTITY:
        raise ValueError("身份ID 不可使用保留字 unknown / stranger")
    return pid


def _extract_face_or_raise(image_bgr: np.ndarray) -> np.ndarray:
    if not face_engine.is_available():
        raise RuntimeError("人脸识别模型未就绪，请检查 models/buffalo_l/")
    emb = face_engine.extract_single_face_embedding(image_bgr)
    if emb is not None:
        return emb
    faces = face_engine.analyze_faces(image_bgr, max_faces=3)
    if len(faces) == 0:
        raise ValueError("未检测到人脸，请上传正面清晰照片")
    if len(faces) > 1:
        raise ValueError("检测到多张人脸，请上传仅含单人的照片")
    raise ValueError("无法提取人脸特征")


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _normalize_embedding(vec: np.ndarray) -> np.ndarray:
    v = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(v))
    if norm > 1e-8:
        v = v / norm
    return v


def _embedding_to_list(vec: np.ndarray) -> List[float]:
    return _normalize_embedding(vec).tolist()


def _embedding_from_meta(meta: Dict[str, Any]) -> Optional[np.ndarray]:
    raw = meta.get("embedding")
    if raw is None:
        for ph in meta.get("photos") or []:
            if ph.get("embedding"):
                raw = ph.get("embedding")
                break
    if raw is None:
        return None
    try:
        return _normalize_embedding(np.asarray(raw, dtype=np.float32))
    except (TypeError, ValueError):
        return None


def _photo_object_key(person_id: str) -> str:
    store = get_object_storage()
    if store is None:
        raise RuntimeError("对象存储未启用，无法上传人脸照片")
    return store.build_face_library_photo_key(person_id)


def _encode_jpeg(image_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise ValueError("照片编码失败")
    return buf.tobytes()


def _public_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    out = json.loads(json.dumps(meta, ensure_ascii=False))
    out.pop("embedding", None)
    return out


def _load_embeddings_from_meta(person_id: str, meta: Dict[str, Any]) -> None:
    emb = _embedding_from_meta(meta)
    if emb is not None:
        _embeddings.append((person_id, emb))


def _migrate_legacy_local_if_needed() -> int:
    """Redis 为空时，将本地 face_library/ 迁移到 Redis + MinIO。"""
    if not redis_manager.is_connected():
        return 0
    if redis_manager.get_all_face_persons():
        return 0

    root = _legacy_lib_root()
    idx_path = os.path.join(root, "index.json")
    if not os.path.isfile(idx_path):
        return 0

    store = get_object_storage()
    if store is None:
        logger.warning("本地人脸库存在但对象存储未启用，跳过迁移")
        return 0

    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        persons_meta = list(data.get("persons") or [])
    except Exception as ex:  # noqa: BLE001
        logger.warning("读取本地人脸库索引失败: %s", ex)
        return 0

    migrated = 0
    for item in persons_meta:
        pid = str(item.get("id") or "").strip()
        if not pid:
            continue
        pdir = _legacy_person_dir(pid)
        meta_path = os.path.join(pdir, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue

        emb_vec: Optional[np.ndarray] = None
        photo_bytes: Optional[bytes] = None
        for ph in meta.get("photos") or []:
            emb_rel = ph.get("embedding")
            img_rel = ph.get("file")
            if emb_rel:
                emb_path = os.path.join(pdir, emb_rel)
                if os.path.isfile(emb_path):
                    try:
                        emb_vec = _normalize_embedding(np.load(emb_path))
                    except Exception:
                        pass
            if img_rel and photo_bytes is None:
                img_path = os.path.join(pdir, img_rel)
                if os.path.isfile(img_path):
                    with open(img_path, "rb") as imgf:
                        photo_bytes = imgf.read()

        if emb_vec is None:
            continue
        if not photo_bytes:
            img_path = os.path.join(pdir, "photo.jpg")
            if os.path.isfile(img_path):
                with open(img_path, "rb") as imgf:
                    photo_bytes = imgf.read()
        if not photo_bytes:
            logger.warning("迁移跳过 %s：无照片文件", pid)
            continue

        object_key = _photo_object_key(pid)
        try:
            store.upload_bytes(photo_bytes, object_key, content_type="image/jpeg")
        except Exception as ex:  # noqa: BLE001
            logger.warning("迁移 %s 上传 MinIO 失败: %s", pid, ex)
            continue

        now = meta.get("updated_at") or datetime.now().isoformat(timespec="seconds")
        redis_meta = {
            "id": pid,
            "identity_id": str(meta.get("identity_id") or pid),
            "name": meta.get("name", ""),
            "department": meta.get("department", ""),
            "remark": meta.get("remark", ""),
            "photos": [
                {
                    "id": "photo_1",
                    "object_key": object_key,
                    "storage_kind": store.kind,
                    "created_at": meta.get("created_at") or now,
                }
            ],
            "embedding": _embedding_to_list(emb_vec),
            "created_at": meta.get("created_at") or now,
            "updated_at": now,
        }
        if redis_manager.save_face_person(pid, redis_meta):
            migrated += 1

    if migrated:
        logger.info("已从本地 face_library/ 迁移 %d 人到 Redis+MinIO", migrated)
    return migrated


def reload_index() -> None:
    global _index, _embeddings
    if not redis_manager.is_connected():
        logger.warning("Redis 未连接，人脸库内存索引为空")
        with _lock:
            _index = {}
            _embeddings = []
        return

    try:
        _migrate_legacy_local_if_needed()
    except Exception as ex:  # noqa: BLE001
        logger.warning("本地人脸库迁移失败（可稍后重试）: %s", ex)

    new_index: Dict[str, Dict[str, Any]] = {}
    new_embeddings: List[Tuple[str, np.ndarray]] = []

    for pid, meta in redis_manager.get_all_face_persons().items():
        if not pid or not meta:
            continue
        new_index[pid] = meta
        emb = _embedding_from_meta(meta)
        if emb is not None:
            new_embeddings.append((pid, emb))

    with _lock:
        _index = new_index
        _embeddings = new_embeddings
    logger.info("人脸库已从 Redis 加载: %d 人, %d 条特征", len(_index), len(_embeddings))


def list_persons() -> List[Dict[str, Any]]:
    with _lock:
        out = []
        for pid, meta in _index.items():
            out.append(
                {
                    "id": pid,
                    "identity_id": str(meta.get("identity_id") or pid),
                    "name": meta.get("name", ""),
                    "department": meta.get("department", ""),
                    "remark": meta.get("remark", ""),
                    "photos": len(meta.get("photos") or []),
                    "created_at": meta.get("created_at", ""),
                    "updated_at": meta.get("updated_at", ""),
                }
            )
        out.sort(key=lambda x: x.get("name", ""))
        return out


def get_person(person_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        meta = _index.get(person_id)
        if not meta:
            return None
        return _public_meta(meta)


def person_count() -> int:
    with _lock:
        return len(_index)


def embedding_count() -> int:
    with _lock:
        return len(_embeddings)


def match_embedding(
    embedding: np.ndarray,
    *,
    threshold: float,
    watchlist: Optional[List[str]] = None,
) -> Tuple[Optional[str], float]:
    vec = _normalize_embedding(embedding)
    watch = None
    if watchlist:
        watch = {str(x).strip() for x in watchlist if str(x).strip()}

    best_pid: Optional[str] = None
    best_sim = -1.0
    per_person: Dict[str, float] = {}

    with _lock:
        for pid, emb in _embeddings:
            if watch is not None and pid not in watch:
                continue
            sim = _cosine_similarity(vec, emb)
            per_person[pid] = max(per_person.get(pid, -1.0), sim)

    for pid, sim in per_person.items():
        if sim > best_sim:
            best_sim = sim
            best_pid = pid

    if best_pid is None or best_sim < threshold:
        return None, best_sim if best_sim >= 0 else 0.0
    return best_pid, best_sim


def rank_embedding(
    embedding: np.ndarray,
    *,
    watchlist: Optional[List[str]] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """1:N 余弦相似度排序（不过阈值），供手动比对展示候选。"""
    vec = _normalize_embedding(embedding)
    watch = None
    if watchlist:
        watch = {str(x).strip() for x in watchlist if str(x).strip()}

    per_person: Dict[str, float] = {}
    with _lock:
        for pid, emb in _embeddings:
            if watch is not None and pid not in watch:
                continue
            sim = _cosine_similarity(vec, emb)
            per_person[pid] = max(per_person.get(pid, -1.0), sim)
        metas = {
            pid: _public_meta(_index[pid])
            for pid in per_person
            if pid in _index
        }

    k = max(1, min(int(top_k or 5), 20))
    ranked = sorted(per_person.items(), key=lambda x: x[1], reverse=True)[:k]
    out: List[Dict[str, Any]] = []
    for pid, sim in ranked:
        meta = metas.get(pid) or {}
        out.append(
            {
                "person_id": pid,
                "identity_id": str(meta.get("identity_id") or pid),
                "name": str(meta.get("name") or pid),
                "department": str(meta.get("department") or ""),
                "similarity": round(float(sim), 4),
            }
        )
    return out


def _preview_jpeg_data_url(image_bgr: np.ndarray, max_width: int = 960) -> str:
    img = image_bgr
    h, w = img.shape[:2]
    if w > max_width > 0:
        nh = max(1, int(round(h * max_width / float(w))))
        img = cv2.resize(img, (max_width, nh))
    raw = _encode_jpeg(img)
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _annotate_compare_faces(image_bgr: np.ndarray, faces: List[Dict[str, Any]]) -> np.ndarray:
    vis = image_bgr.copy()
    for item in faces:
        box = item.get("bbox") or [0, 0, 0, 0]
        try:
            x1, y1, x2, y2 = [int(v) for v in box[:4]]
        except (TypeError, ValueError):
            continue
        matched = bool(item.get("matched"))
        color = (46, 160, 67) if matched else (50, 50, 210)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        best = item.get("best") or {}
        ident = str(best.get("identity_id") or "")
        sim = best.get("similarity")
        if ident and sim is not None:
            tag = f"{ident} {float(sim):.2f}"
        else:
            tag = f"face{int(item.get('index') or 0)}"
        ytxt = y1 - 6 if y1 > 18 else y2 + 16
        cv2.putText(
            vis,
            tag,
            (x1, ytxt),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    return vis


def compare_image(
    image_bgr: np.ndarray,
    *,
    threshold: Optional[float] = None,
    top_k: int = 5,
    max_faces: Optional[int] = None,
    person_id: Optional[str] = None,
) -> Dict[str, Any]:
    """对探测图做人脸检测 + 与库内已录入人员 1:N（或指定 1:1）比对。"""
    from visionai.config.settings import (
        FACE_RECOGNITION_MAX_FACES_PER_FRAME,
        FACE_RECOGNITION_THRESHOLD,
    )

    if not face_engine.is_available():
        raise RuntimeError("人脸识别模型未就绪，请检查 models/buffalo_l/")
    if image_bgr is None or getattr(image_bgr, "size", 0) == 0:
        raise ValueError("图片无效")

    if threshold is None:
        thr = float(FACE_RECOGNITION_THRESHOLD)
    else:
        try:
            thr = float(threshold)
        except (TypeError, ValueError) as ex:
            raise ValueError("阈值无效") from ex
        if thr < 0 or thr > 1:
            raise ValueError("阈值须在 0～1 之间")

    watch: Optional[List[str]] = None
    scope = "all"
    pid = str(person_id or "").strip()
    if pid:
        if get_person(pid) is None:
            raise ValueError("指定人员不存在")
        watch = [pid]
        scope = pid

    nfaces = int(max_faces or FACE_RECOGNITION_MAX_FACES_PER_FRAME)
    detected = face_engine.analyze_faces(image_bgr, max_faces=max(1, nfaces))
    faces: List[Dict[str, Any]] = []
    for det in detected:
        ranked = rank_embedding(det["embedding"], watchlist=watch, top_k=top_k)
        for cand in ranked:
            cand["matched"] = float(cand["similarity"]) >= thr
            cand["photo_url"] = (
                "/api/face-library/" + str(cand["person_id"]) + "/photo"
            )
        best = ranked[0] if ranked else None
        box = [int(v) for v in (det.get("bbox") or [0, 0, 0, 0])[:4]]
        faces.append(
            {
                "index": int(det.get("index") or 0),
                "bbox": box,
                "det_score": round(float(det.get("det_score") or 0.0), 4),
                "matched": bool(best and best.get("matched")),
                "best": best,
                "candidates": ranked,
            }
        )
    vis = _annotate_compare_faces(image_bgr, faces)
    return {
        "threshold": round(float(thr), 4),
        "library_count": person_count(),
        "face_count": len(faces),
        "scope": scope,
        "query_jpeg": _preview_jpeg_data_url(vis),
        "faces": faces,
    }


def person_name(person_id: Optional[str]) -> str:
    if not person_id:
        return "陌生人"
    with _lock:
        meta = _index.get(person_id)
        if not meta:
            return "陌生人"
        return str(meta.get("name") or person_id)


def person_department(person_id: Optional[str]) -> str:
    pid = resolve_person_id(person_id)
    if pid == UNKNOWN_PERSON_ID:
        return ""
    with _lock:
        meta = _index.get(pid)
        if not meta:
            return ""
        return str(meta.get("department") or "")


def person_identity_id(person_id: Optional[str]) -> str:
    pid = resolve_person_id(person_id)
    if pid == UNKNOWN_PERSON_ID:
        return UNKNOWN_PERSON_ID
    with _lock:
        meta = _index.get(pid)
        if not meta:
            return pid
        return str(meta.get("identity_id") or pid)


def enroll_person(
    image_bgr: np.ndarray,
    *,
    name: str,
    identity_id: str,
    department: str = "",
    remark: str = "",
) -> Dict[str, Any]:
    if not redis_manager.is_connected():
        raise RuntimeError("Redis 未连接，无法保存人脸库")
    if not face_engine.is_available():
        raise RuntimeError("人脸识别模型未就绪，请检查 models/buffalo_l/")

    pid = validate_identity_id(identity_id)
    store = get_object_storage()
    if store is None:
        raise RuntimeError("对象存储未启用，无法上传人脸照片（请配置 MinIO/S3）")

    emb = _extract_face_or_raise(image_bgr)

    with _lock:
        if pid in _index:
            raise ValueError("身份ID 已存在")

    now = datetime.now().isoformat(timespec="seconds")
    object_key = _photo_object_key(pid)
    jpeg_bytes = _encode_jpeg(image_bgr)
    store.upload_bytes(jpeg_bytes, object_key, content_type="image/jpeg")

    meta = {
        "id": pid,
        "identity_id": pid,
        "name": (name or "").strip() or "未命名",
        "department": (department or "").strip(),
        "remark": (remark or "").strip(),
        "photos": [
            {
                "id": "photo_1",
                "object_key": object_key,
                "storage_kind": store.kind,
                "created_at": now,
            }
        ],
        "embedding": _embedding_to_list(emb),
        "created_at": now,
        "updated_at": now,
    }
    if not redis_manager.save_face_person(pid, meta):
        store.delete_object(object_key)
        raise RuntimeError("保存人脸库到 Redis 失败")

    with _lock:
        if pid in _index:
            store.delete_object(object_key)
            raise ValueError("身份ID 已存在")
        _index[pid] = meta
        _embeddings.append((pid, _normalize_embedding(emb)))

    return {"id": pid, "identity_id": pid, "name": meta["name"], "message": "录入成功"}


def _photo_keys(meta: Dict[str, Any]) -> List[str]:
    keys = []
    for ph in meta.get("photos") or []:
        okey = ph.get("object_key")
        if okey:
            keys.append(str(okey))
    return keys


def _set_photo_meta(meta: Dict[str, Any], person_id: str, object_key: str, storage_kind: str, now: str) -> None:
    meta["photos"] = [
        {
            "id": "photo_1",
            "object_key": object_key,
            "storage_kind": storage_kind,
            "created_at": now,
        }
    ]


def update_person(
    person_id: str,
    *,
    name: Optional[str] = None,
    department: Optional[str] = None,
    remark: Optional[str] = None,
    identity_id: Optional[str] = None,
    image_bgr: Optional[np.ndarray] = None,
) -> Optional[Dict[str, Any]]:
    """更新人员资料。可改身份ID、姓名、部门、备注，以及可选换照片（同时重提特征）。"""
    old_id = str(person_id or "").strip()
    if not old_id:
        return None
    with _lock:
        src = _index.get(old_id)
        if not src:
            return None
        meta = json.loads(json.dumps(src, ensure_ascii=False))

    new_id = old_id
    if identity_id is not None:
        new_id = validate_identity_id(identity_id)
        if new_id != old_id:
            with _lock:
                if new_id in _index:
                    raise ValueError("身份ID 已存在")

    now = datetime.now().isoformat(timespec="seconds")
    if name is not None:
        meta["name"] = str(name).strip() or str(meta.get("name") or "未命名")
    if department is not None:
        meta["department"] = str(department).strip()
    if remark is not None:
        meta["remark"] = str(remark).strip()

    store = get_object_storage()
    old_keys = _photo_keys(meta)
    new_object_key = None

    if image_bgr is not None:
        if store is None:
            raise RuntimeError("对象存储未启用，无法更新人脸照片")
        emb = _extract_face_or_raise(image_bgr)
        new_object_key = _photo_object_key(new_id)
        store.upload_bytes(_encode_jpeg(image_bgr), new_object_key, content_type="image/jpeg")
        _set_photo_meta(meta, new_id, new_object_key, store.kind, now)
        meta["embedding"] = _embedding_to_list(emb)
    elif new_id != old_id:
        if store is None:
            raise RuntimeError("对象存储未启用，无法迁移人脸照片")
        photo_bytes = get_photo_bytes(old_id)
        if photo_bytes:
            new_object_key = _photo_object_key(new_id)
            store.upload_bytes(photo_bytes, new_object_key, content_type="image/jpeg")
            _set_photo_meta(meta, new_id, new_object_key, store.kind, now)

    meta["id"] = new_id
    meta["identity_id"] = new_id
    meta["updated_at"] = now

    if not redis_manager.save_face_person(new_id, meta):
        raise RuntimeError("保存人脸库到 Redis 失败")
    if new_id != old_id:
        redis_manager.delete_face_person(old_id)

    if store and new_object_key:
        for okey in old_keys:
            if okey != new_object_key:
                try:
                    store.delete_object(okey)
                except Exception as ex:  # noqa: BLE001
                    logger.warning("删除旧人脸照片失败 %s: %s", okey, ex)

    emb = _embedding_from_meta(meta)
    with _lock:
        _index.pop(old_id, None)
        _index[new_id] = meta
        rest = [(p, e) for p, e in _embeddings if p != old_id]
        if emb is not None:
            rest.append((new_id, emb))
        _embeddings[:] = rest

    return _public_meta(meta)


def delete_person(person_id: str) -> bool:
    """删除人员。内存或 Redis 任一侧有记录即可删除（避免 Redis 丢键后删不掉）。"""
    with _lock:
        meta = _index.get(person_id)
    if not meta:
        meta = redis_manager.get_face_person(person_id)
    if not meta:
        # Redis 已无此人时仍清理可能残留的内存索引
        with _lock:
            existed = person_id in _index
            _index.pop(person_id, None)
            _embeddings[:] = [(p, e) for p, e in _embeddings if p != person_id]
        return existed

    store = get_object_storage()
    for ph in meta.get("photos") or []:
        okey = ph.get("object_key")
        if okey and store:
            try:
                store.delete_object(okey)
            except Exception as ex:  # noqa: BLE001
                logger.warning("删除人脸照片对象失败 %s: %s", okey, ex)

    # Redis 键可能已丢失：hdel=0 不视为失败
    redis_manager.delete_face_person(person_id)

    with _lock:
        _index.pop(person_id, None)
        _embeddings[:] = [(p, e) for p, e in _embeddings if p != person_id]
    return True


def get_photo_bytes(person_id: str) -> Optional[bytes]:
    with _lock:
        meta = _index.get(person_id)
    if not meta:
        meta = redis_manager.get_face_person(person_id)
    if not meta:
        return None

    store = get_object_storage()
    for ph in meta.get("photos") or []:
        okey = ph.get("object_key")
        if okey and store:
            try:
                return store.get_object_bytes(okey)
            except Exception as ex:  # noqa: BLE001
                logger.warning("从对象存储读取照片失败 %s: %s", okey, ex)

    legacy = os.path.join(_legacy_person_dir(person_id), "photo.jpg")
    if os.path.isfile(legacy):
        with open(legacy, "rb") as f:
            return f.read()
    return None


def photo_path(person_id: str) -> Optional[str]:
    """兼容旧接口；Redis+MinIO 模式下返回 None，请用 get_photo_bytes。"""
    legacy = os.path.join(_legacy_person_dir(person_id), "photo.jpg")
    return legacy if os.path.isfile(legacy) else None


def recompute_all_embeddings() -> int:
    if not face_engine.is_available():
        return 0
    updated = 0
    with _lock:
        person_ids = list(_index.keys())
    for pid in person_ids:
        photo_bytes = get_photo_bytes(pid)
        if not photo_bytes:
            continue
        arr = np.frombuffer(photo_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        emb = face_engine.extract_single_face_embedding(img)
        if emb is None:
            logger.warning("重新提取特征失败: %s", pid)
            continue
        with _lock:
            meta = _index.get(pid)
            if not meta:
                continue
            meta["embedding"] = _embedding_to_list(emb)
            meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if redis_manager.save_face_person(pid, meta):
            updated += 1
    reload_index()
    logger.info("人脸库特征已重新计算: %d 条", updated)
    return updated


try:
    reload_index()
except Exception as _ex:  # noqa: BLE001
    logger.warning("人脸库初始加载失败: %s", _ex)
