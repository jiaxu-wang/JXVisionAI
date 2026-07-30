"""gRPC client for visionai-inferd (UDS)."""

from __future__ import annotations

import logging
import threading
from typing import List, Optional, Sequence

import numpy as np

from visionai.core.infer_types import DetectionBox, InferResult

logger = logging.getLogger(__name__)

_pb2 = None
_pb2_grpc = None
_grpc = None


def _ensure_stubs():
    global _pb2, _pb2_grpc, _grpc
    if _pb2 is not None:
        return
    try:
        import grpc
        from visionai.core.infer_proto import infer_pb2, infer_pb2_grpc
    except ImportError as e:
        raise RuntimeError(
            "cpp infer backend requires grpcio; pip install grpcio grpcio-tools "
            "or ensure PYTHONPATH includes .pip_target"
        ) from e
    _grpc = grpc
    _pb2 = infer_pb2
    _pb2_grpc = infer_pb2_grpc


class InferClient:
    def __init__(self, endpoint: str = "unix:///tmp/visionai-inferd.sock", timeout_s: float = 30.0):
        _ensure_stubs()
        self.endpoint = endpoint
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._channel = None
        self._stub = None
        self._fallback_yolo = None

    def connect(self) -> None:
        with self._lock:
            if self._stub is not None:
                return
            self._channel = _grpc.insecure_channel(self.endpoint)
            self._stub = _pb2_grpc.InferServiceStub(self._channel)

    def close(self) -> None:
        with self._lock:
            if self._channel is not None:
                self._channel.close()
            self._channel = None
            self._stub = None

    def live(self) -> bool:
        self.connect()
        resp = self._stub.Live(_pb2.LiveRequest(), timeout=self.timeout_s)
        return bool(resp.alive)

    def ready(self) -> bool:
        self.connect()
        resp = self._stub.Ready(_pb2.ReadyRequest(), timeout=self.timeout_s)
        return bool(resp.ready)

    def load_primary(self, version: str = "1", device: str = "") -> None:
        self.connect()
        req = _pb2.LoadModelRequest()
        req.model.name = "primary"
        req.model.version = version
        if device:
            req.model.device = device
        resp = self._stub.LoadModel(req, timeout=self.timeout_s)
        if resp.status.code != _pb2.OK:
            raise RuntimeError(f"LoadModel failed: {resp.status.message}")

    def open_session(
        self,
        session_id: str,
        conf: float = 0.25,
        imgsz: int = 640,
        class_filter: Optional[Sequence[int]] = None,
    ) -> None:
        if not session_id:
            raise ValueError("session_id (stream id) required")
        self.connect()
        req = _pb2.OpenSessionRequest()
        req.config.session_id = session_id
        req.config.model_name = "primary"
        req.config.conf = float(conf)
        req.config.imgsz = int(imgsz)
        if class_filter:
            req.config.class_filter.extend(int(x) for x in class_filter)
        resp = self._stub.OpenSession(req, timeout=self.timeout_s)
        if resp.status.code != _pb2.OK:
            raise RuntimeError(f"OpenSession failed: {resp.status.message}")

    def close_session(self, session_id: str) -> None:
        self.connect()
        req = _pb2.CloseSessionRequest(session_id=session_id)
        self._stub.CloseSession(req, timeout=self.timeout_s)

    def infer(self, session_id: str, frame_bgr: np.ndarray, frame_id: int = 0) -> InferResult:
        self.connect()
        if frame_bgr is None or frame_bgr.size == 0 or frame_bgr.ndim != 3:
            return InferResult(ok=False, error_code="INVALID_ARGUMENT", message="empty frame")
        h, w = frame_bgr.shape[:2]
        req = _pb2.InferRequest()
        req.session_id = session_id
        req.frame_id = int(frame_id)
        img = req.image
        img.height = int(h)
        img.width = int(w)
        img.channels = 3
        img.layout = "HWC"
        img.color = "BGR"
        img.dtype = "UINT8"
        img.data = np.ascontiguousarray(frame_bgr).tobytes()
        try:
            resp = self._stub.Infer(req, timeout=self.timeout_s)
        except Exception as e:  # noqa: BLE001
            return InferResult(ok=False, error_code="BACKEND_FAILURE", message=str(e))
        code_name = _pb2.ErrorCode.Name(resp.status.code)
        if resp.status.code != _pb2.OK:
            return InferResult(
                ok=False,
                error_code=code_name,
                message=resp.status.message,
                frame_id=resp.frame_id,
            )
        boxes: List[DetectionBox] = []
        for d in resp.detections:
            boxes.append(
                DetectionBox(
                    x1=d.x1,
                    y1=d.y1,
                    x2=d.x2,
                    y2=d.y2,
                    class_id=d.class_id,
                    conf=d.conf,
                    label=d.label,
                    model_name=d.model_name or "primary",
                )
            )
        return InferResult(
            ok=True,
            boxes=boxes,
            infer_ms=int(resp.infer_ms),
            error_code="OK",
            frame_id=resp.frame_id,
        )


_client: Optional[InferClient] = None
_client_lock = threading.Lock()


def get_infer_client() -> InferClient:
    """Process-wide shared client (from settings)."""
    global _client
    from visionai.config import settings as S

    with _client_lock:
        if _client is None:
            _client = InferClient(endpoint=S.INFER_ENDPOINT)
        return _client
