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

    def load_model(
        self,
        name: str,
        path: str,
        *,
        task: str = "detect",
        num_classes: int = 80,
        imgsz: int = 640,
        labels: str = "",
        device: str = "",
    ) -> None:
        self.connect()
        req = _pb2.LoadModelRequest()
        req.model.name = name or "primary"
        req.model.version = "1"
        req.model.format = "onnx"
        req.model.path = path
        if device:
            req.model.device = device
        req.model.meta["task"] = task or "detect"
        req.model.meta["num_classes"] = str(int(num_classes))
        req.model.meta["imgsz"] = str(int(imgsz))
        if labels:
            req.model.meta["labels"] = labels
        resp = self._stub.LoadModel(req, timeout=max(self.timeout_s, 120.0))
        if resp.status.code != _pb2.OK:
            raise RuntimeError(f"LoadModel failed: {resp.status.message}")

    def unload_model(self, name: str) -> None:
        self.connect()
        req = _pb2.UnloadModelRequest(name=name, version="1")
        self._stub.UnloadModel(req, timeout=self.timeout_s)

    def open_session(
        self,
        session_id: str,
        conf: float = 0.25,
        imgsz: int = 640,
        class_filter: Optional[Sequence[int]] = None,
        model_name: str = "primary",
    ) -> None:
        if not session_id:
            raise ValueError("session_id required")
        self.connect()
        req = _pb2.OpenSessionRequest()
        req.config.session_id = session_id
        req.config.model_name = model_name or "primary"
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
                    keypoints=list(d.keypoint),
                )
            )
        return InferResult(
            ok=True,
            boxes=boxes,
            infer_ms=int(resp.infer_ms),
            error_code="OK",
            frame_id=resp.frame_id,
        )

    def analyze_face(
        self,
        frame_bgr: np.ndarray,
        *,
        det_model: str,
        embed_model: str = "",
        genderage_model: str = "",
        det_conf: float = 0.5,
        det_size: int = 640,
        max_faces: int = 5,
        with_embedding: bool = True,
        with_genderage: bool = False,
    ):
        self.connect()
        h, w = frame_bgr.shape[:2]
        req = _pb2.AnalyzeFaceRequest()
        img = req.image
        img.height = int(h)
        img.width = int(w)
        img.channels = 3
        img.layout = "HWC"
        img.color = "BGR"
        img.dtype = "UINT8"
        img.data = np.ascontiguousarray(frame_bgr).tobytes()
        req.det_model = det_model
        req.embed_model = embed_model or ""
        req.genderage_model = genderage_model or ""
        req.det_conf = float(det_conf)
        req.det_size = int(det_size)
        req.max_faces = int(max_faces)
        req.with_embedding = bool(with_embedding)
        req.with_genderage = bool(with_genderage)
        resp = self._stub.AnalyzeFace(req, timeout=self.timeout_s)
        if resp.status.code != _pb2.OK:
            raise RuntimeError(f"AnalyzeFace failed: {resp.status.message}")
        return resp


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
