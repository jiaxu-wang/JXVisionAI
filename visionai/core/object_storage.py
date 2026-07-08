"""S3 兼容对象存储（MinIO、AWS、阿里云 OSS 等），可扩展为其他后端。"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_SAFE_SEG = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_segment(name: str) -> str:
    s = (name or "unknown").strip().replace("/", "_").replace("\\", "_")
    return _SAFE_SEG.sub("_", s) or "stream"


@dataclass
class UploadResult:
    """上传结果，供 Redis 与后续扩展复用。"""

    key: str
    uri: str
    kind: str = "s3"

    @property
    def object_key(self) -> str:
        return self.key


@runtime_checkable
class ObjectStorageBackend(Protocol):
    """对象存储协议：后续可新增 Azure Blob、GCS 等实现。"""

    kind: str

    def upload_file(
        self, local_path: str, object_key: str, *, content_type: Optional[str] = None, extra: Optional[dict] = None
    ) -> UploadResult:
        ...

    def delete_object(self, object_key: str) -> bool:
        ...

    def get_object_bytes(self, object_key: str) -> bytes:
        ...


class S3CompatibleStorage:
    """Boto3 S3 兼容（MinIO / AWS S3 等）。"""

    kind = "s3"

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        from visionai.config.settings import (
            S3_ACCESS_KEY_ID,
            S3_ADDRESSING_STYLE,
            S3_BUCKET,
            S3_ENDPOINT_URL,
            S3_LIFECYCLE_ENABLED,
            S3_PATH_PREFIX,
            S3_REGION,
            S3_SECRET_ACCESS_KEY,
            S3_USE_SSL,
        )
        self._s3_lifecycle_enabled = S3_LIFECYCLE_ENABLED

        self._bucket = S3_BUCKET
        self._prefix = S3_PATH_PREFIX

        cfg = Config(
            signature_version="s3v4",
            s3={"addressing_style": S3_ADDRESSING_STYLE},
        )
        kwargs: dict[str, Any] = {
            "config": cfg,
            "region_name": S3_REGION,
            "use_ssl": S3_USE_SSL,
        }
        if S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = S3_ENDPOINT_URL
        if S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = S3_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = S3_SECRET_ACCESS_KEY

        self._client = boto3.client("s3", **kwargs)
        self._ensure_bucket()
        self._apply_lifecycle()
        logger.info("对象存储 (S3 兼容) 已就绪: bucket=%s", self._bucket)

    def _ensure_bucket(self) -> None:
        """尽力创建桶；不抛异常，避免 MinIO 尚未就绪时导致进程放弃对象存储。"""
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            self._client.create_bucket(Bucket=self._bucket)
            logger.info("已创建对象存储桶: %s", self._bucket)
        except Exception as e:  # noqa: BLE001
            if "BucketAlreadyOwnedByYou" in str(e) or "BucketAlreadyExists" in str(e):
                return
            logger.warning("对象存储桶暂不可用（稍后将重试）: %s: %s", self._bucket, e)

    def _apply_lifecycle(self) -> None:
        """
        为截图前缀设置桶生命周期：对象在创建满 DETECTION_RETENTION_DAYS 天后删除。
        MinIO 与 S3 均支持；与 get/merge 已有规则，避免清掉同桶内其它业务的手动规则。
        """
        if not self._s3_lifecycle_enabled:
            return
        from botocore.exceptions import ClientError

        from visionai.config.settings import DETECTION_RETENTION_DAYS

        days = max(1, int(DETECTION_RETENTION_DAYS))
        snap_prefix = f"{self._prefix}snapshots/"
        rule_id = "visionai-snapshots-match-detention-retention"
        new_rule: dict[str, Any] = {
            "ID": rule_id,
            "Status": "Enabled",
            "Filter": {"Prefix": snap_prefix},
            "Expiration": {"Days": days},
        }
        rules: list = []
        try:
            r = self._client.get_bucket_lifecycle_configuration(Bucket=self._bucket)
            rules = [x for x in r.get("Rules", []) if x.get("ID") != rule_id]
        except ClientError as e:
            err = (e.response or {}).get("Error", {}) or {}
            code = str(err.get("Code", ""))
            if "NoSuchLifecycle" in code or code in ("NoSuchKey", "404", "NotFound"):
                rules = []
            else:
                logger.warning(
                    "未读取到已有桶生命周期，跳过自动写入（避免覆盖云端策略）: %s",
                    e,
                )
                return
        except Exception as e:  # noqa: BLE001
            logger.warning("未读取到已有桶生命周期，跳过自动写入: %s", e)
            return
        rules.append(new_rule)
        try:
            self._client.put_bucket_lifecycle_configuration(
                Bucket=self._bucket,
                LifecycleConfiguration={"Rules": rules},
            )
            logger.info(
                "对象存储生命周期: 前缀 %r 在 %s 天删除（与 detection_retention_days 一致，"
                "按对象「上传后」起算，见 README 说明）",
                snap_prefix,
                days,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "无法写入桶生命周期，可在 MinIO/云控制台为前缀 %s 配置 %s 天过期: %s",
                snap_prefix,
                days,
                e,
            )

    def build_snapshot_key(self, stream_id: str, filename: str) -> str:
        """对象键中目录名使用流 ID（如 stream_938a7923），勿用显示名称（中文等会被压成下划线）。"""
        seg = _safe_segment(stream_id) or "unknown"
        return f"{self._prefix}snapshots/{seg}/{filename}"

    def build_key(self, category: str, *parts: str) -> str:
        """扩展用：如 video 上传 build_key('videos', stream, name)。"""
        segs = "/".join(_safe_segment(p) for p in parts)
        return f"{self._prefix}{category.strip('/')}/{segs}"

    def upload_file(
        self, local_path: str, object_key: str, *, content_type: Optional[str] = None, extra: Optional[dict] = None
    ) -> UploadResult:
        extra = extra or {}
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)
        ex: dict[str, str] = {}
        if content_type:
            ex["ContentType"] = content_type
        if ex:
            self._client.upload_file(local_path, self._bucket, object_key, ExtraArgs=ex)
        else:
            self._client.upload_file(local_path, self._bucket, object_key)
        uri = f"s3://{self._bucket}/{object_key}"
        logger.info("已上传对象: %s", object_key)
        return UploadResult(key=object_key, uri=uri, kind=self.kind)

    def delete_object(self, object_key: str) -> bool:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
            logger.info("已删除对象: %s", object_key)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("删除对象失败 %s: %s", object_key, e)
            return False

    def get_object_bytes(self, object_key: str) -> bytes:
        r = self._client.get_object(Bucket=self._bucket, Key=object_key)
        return r["Body"].read()

    def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        *,
        content_type: Optional[str] = None,
    ) -> UploadResult:
        ex: dict[str, str] = {}
        if content_type:
            ex["ContentType"] = content_type
        if ex:
            self._client.put_object(
                Bucket=self._bucket, Key=object_key, Body=data, **ex
            )
        else:
            self._client.put_object(Bucket=self._bucket, Key=object_key, Body=data)
        uri = f"s3://{self._bucket}/{object_key}"
        logger.info("已上传对象: %s (%d bytes)", object_key, len(data))
        return UploadResult(key=object_key, uri=uri, kind=self.kind)

    def build_face_library_photo_key(self, person_id: str, filename: str = "photo.jpg") -> str:
        return self.build_key("face_library", person_id, filename)


_storage: Optional[S3CompatibleStorage] = None
_init_failed: bool = False


def get_object_storage() -> Optional[S3CompatibleStorage]:
    """若未启用或缺少必要配置，返回 None。"""
    global _storage, _init_failed
    from visionai.config.settings import (
        OBJECT_STORAGE_ENABLED,
        S3_ACCESS_KEY_ID,
        S3_BUCKET,
        S3_SECRET_ACCESS_KEY,
    )

    if not OBJECT_STORAGE_ENABLED:
        return None
    if not S3_BUCKET:
        return None
    if _init_failed:
        return None
    if _storage is not None:
        return _storage
    if not S3_ACCESS_KEY_ID or not S3_SECRET_ACCESS_KEY:
        logger.warning("对象存储已启用但缺少 S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY")
        _init_failed = True
        return None
    try:
        _storage = S3CompatibleStorage()
    except Exception as e:  # noqa: BLE001
        logger.error("初始化 S3 客户端失败: %s", e, exc_info=True)
        _init_failed = True
        return None
    return _storage
