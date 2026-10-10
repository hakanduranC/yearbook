"""Lazy, per-process model hub: every model is loaded once, on first use, from `WORKER_MODELS_DIR`.

CPU only. Shared by the `analyze` stages, the clusterer (no models) and the ML server. Download
locations: Hugging Face models under `<models_dir>/hf` (HF_HOME), the InsightFace pack under
`<models_dir>/insightface/models/<pack>`. Nothing is baked into the container image.
"""

from __future__ import annotations

import os
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from yearbook_worker.config import Settings
from yearbook_worker.log import get_logger

log = get_logger(__name__)

INSIGHTFACE_RELEASE = "https://github.com/deepinsight/insightface/releases/download/model-zoo/"
EMBED_DIM = 1152
FACE_DIM = 512


@dataclass(slots=True)
class SiglipVision:
    model: Any
    processor: Any
    name: str


@dataclass(slots=True)
class SiglipText:
    model: Any
    tokenizer: Any
    name: str


@dataclass(slots=True)
class Florence:
    model: Any
    processor: Any
    name: str


@dataclass(slots=True)
class RawFace:
    """One detection on a BGR image: everything in that image's pixel space."""

    bbox: np.ndarray  # x1, y1, x2, y2 float
    kps: np.ndarray  # 5x2 (left eye, right eye, nose, mouth left, mouth right)
    det_score: float
    landmarks: np.ndarray  # 106x2
    embedding: np.ndarray  # 512, L2-normalised
    aligned: np.ndarray  # 112x112 BGR crop used for the embedding


class FaceEngine:
    """InsightFace antelopev2: SCRFD-10GF detector, 2d106 landmarks, ArcFace (glint R100).

    The three ONNX sessions are created directly (not via `FaceAnalysis`) so the session options
    are ours: thread spinning off, which halves the latency on hybrid laptop CPUs.
    """

    def __init__(self, pack_dir: Path, det_size: int, det_thresh: float) -> None:
        import onnxruntime as ort
        from insightface.model_zoo import model_zoo

        so = ort.SessionOptions()
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        kw = {"providers": ["CPUExecutionProvider"], "session_options": so}
        by_task: dict[str, Any] = {}
        for onnx in sorted(pack_dir.glob("*.onnx")):
            model = model_zoo.get_model(str(onnx), **kw)
            if model is not None and model.taskname not in by_task:
                by_task[model.taskname] = model
        missing = {"detection", "recognition", "landmark_2d_106"} - set(by_task)
        if missing:
            raise RuntimeError(f"face pack {pack_dir} lacks {sorted(missing)}")
        self.det = by_task["detection"]
        self.det.prepare(ctx_id=0, det_thresh=det_thresh, input_size=(det_size, det_size))
        self.rec = by_task["recognition"]
        self.rec.prepare(ctx_id=0)
        self.lmk = by_task["landmark_2d_106"]
        self.lmk.prepare(ctx_id=0)

    def detect(self, bgr: np.ndarray, *, max_faces: int = 50) -> list[RawFace]:
        from insightface.app.common import Face
        from insightface.utils import face_align

        bboxes, kpss = self.det.detect(bgr, max_num=max_faces, metric="default")
        if bboxes is None or len(bboxes) == 0:
            return []
        aligned = [face_align.norm_crop(bgr, landmark=k, image_size=112) for k in kpss]
        feats = np.asarray(self.rec.get_feat(aligned), dtype=np.float32).reshape(len(aligned), -1)
        norms = np.linalg.norm(feats, axis=1, keepdims=True)
        feats = feats / np.maximum(norms, 1e-6)
        out: list[RawFace] = []
        for i, (bbox, kps) in enumerate(zip(bboxes, kpss, strict=True)):
            face = Face(bbox=bbox[:4], kps=kps, det_score=float(bbox[4]))
            self.lmk.get(bgr, face)
            out.append(
                RawFace(
                    bbox=np.asarray(bbox[:4], dtype=np.float32),
                    kps=np.asarray(kps, dtype=np.float32),
                    det_score=float(bbox[4]),
                    landmarks=np.asarray(face.landmark_2d_106, dtype=np.float32),
                    embedding=feats[i],
                    aligned=aligned[i],
                )
            )
        return out


class ModelHub:
    """Thread-safe lazy loaders. Attribute access never loads; call the methods."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.models_dir = Path(settings.worker_models_dir).expanduser()
        self._lock = threading.Lock()
        self._faces: FaceEngine | None = None
        self._siglip_vision: SiglipVision | None = None
        self._siglip_text: SiglipText | None = None
        self._florence: Florence | None = None
        self._age: Any = None
        self._env_ready = False

    # -- environment -------------------------------------------------------------------

    def prepare_env(self) -> None:
        """Point HF and torch at the models dir and the CPU; idempotent, cheap."""
        if self._env_ready:
            return
        self.models_dir.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(self.models_dir / "hf")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        import torch

        threads = self.settings.worker_torch_threads or max(1, os.cpu_count() or 1)
        torch.set_num_threads(threads)
        self._env_ready = True

    def loaded(self) -> dict[str, bool]:
        return {
            "faces": self._faces is not None,
            "siglip_vision": self._siglip_vision is not None,
            "siglip_text": self._siglip_text is not None,
            "florence": self._florence is not None,
            "age": self._age is not None,
        }

    # -- faces -------------------------------------------------------------------------

    def faces(self) -> FaceEngine:
        with self._lock:
            if self._faces is None:
                self.prepare_env()
                started = time.perf_counter()
                pack_dir = ensure_insightface_pack(
                    self.models_dir / "insightface", self.settings.worker_face_pack
                )
                self._faces = FaceEngine(
                    pack_dir,
                    det_size=self.settings.worker_face_det_size,
                    det_thresh=min(0.5, self.settings.worker_face_det_thresh),
                )
                log.info(
                    "models.loaded",
                    model=self.settings.worker_face_pack,
                    duration_ms=_ms(started),
                )
            return self._faces

    # -- SigLIP 2 so400m: vision tower for media embeddings, text tower for search -----

    def siglip_vision(self) -> SiglipVision:
        with self._lock:
            if self._siglip_vision is None:
                self.prepare_env()
                started = time.perf_counter()
                import torch
                from transformers import AutoImageProcessor, SiglipVisionModel

                name = self.settings.worker_siglip_model
                model = SiglipVisionModel.from_pretrained(name, dtype=torch.float32).eval()
                processor = AutoImageProcessor.from_pretrained(name)
                self._siglip_vision = SiglipVision(model=model, processor=processor, name=name)
                log.info("models.loaded", model=f"{name}/vision", duration_ms=_ms(started))
            return self._siglip_vision

    def siglip_text(self) -> SiglipText:
        with self._lock:
            if self._siglip_text is None:
                self.prepare_env()
                started = time.perf_counter()
                import torch
                from transformers import AutoTokenizer, SiglipTextModel

                name = self.settings.worker_siglip_model
                model = SiglipTextModel.from_pretrained(name, dtype=torch.float32).eval()
                tokenizer = AutoTokenizer.from_pretrained(name)
                self._siglip_text = SiglipText(model=model, tokenizer=tokenizer, name=name)
                log.info("models.loaded", model=f"{name}/text", duration_ms=_ms(started))
            return self._siglip_text

    def embed_images(self, images: list[Any]) -> np.ndarray:
        """L2-normalised 1152-d SigLIP 2 image embeddings (PIL RGB images)."""
        import torch

        sv = self.siglip_vision()
        with torch.inference_mode():
            px = sv.processor(images=images, return_tensors="pt")["pixel_values"]
            pooled = sv.model(pixel_values=px).pooler_output
            return torch.nn.functional.normalize(pooled, dim=-1).cpu().numpy()

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """L2-normalised 1152-d SigLIP 2 text embeddings (Gemma tokenizer, 64 tokens max)."""
        import torch

        st = self.siglip_text()
        with torch.inference_mode():
            tokens = st.tokenizer(
                texts, padding="max_length", max_length=64, truncation=True, return_tensors="pt"
            )
            pooled = st.model(**tokens).pooler_output
            return torch.nn.functional.normalize(pooled, dim=-1).cpu().numpy()

    # -- Florence-2: caption and OCR ----------------------------------------------------

    def florence(self) -> Florence:
        with self._lock:
            if self._florence is None:
                self.prepare_env()
                started = time.perf_counter()
                import torch
                from transformers import AutoProcessor, Florence2ForConditionalGeneration

                name = self.settings.worker_florence_model
                model = Florence2ForConditionalGeneration.from_pretrained(
                    name, dtype=torch.float32
                ).eval()
                processor = AutoProcessor.from_pretrained(name)
                self._florence = Florence(model=model, processor=processor, name=name)
                log.info("models.loaded", model=name, duration_ms=_ms(started))
            return self._florence

    def florence_task(self, image: Any, task: str, *, max_new_tokens: int) -> str:
        """Run one Florence-2 prompt task (`<MORE_DETAILED_CAPTION>`, `<OCR>`) greedily."""
        import torch

        fl = self.florence()
        inputs = fl.processor(text=task, images=image, return_tensors="pt")
        with torch.inference_mode():
            generated = fl.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=max_new_tokens,
                num_beams=1,
                do_sample=False,
            )
        text = fl.processor.batch_decode(generated, skip_special_tokens=False)[0]
        parsed = fl.processor.post_process_generation(text, task=task, image_size=image.size)
        value = parsed.get(task, "") if isinstance(parsed, dict) else parsed
        return str(value).strip()

    # -- MiVOLO v2: age from face (+ body) crops ------------------------------------------

    def age(self) -> Any:
        with self._lock:
            if self._age is None:
                self.prepare_env()
                started = time.perf_counter()
                from yearbook_worker.mivolo import MiVOLO

                name = self.settings.worker_age_model
                self._age = MiVOLO.from_hub(name)
                log.info("models.loaded", model=name, duration_ms=_ms(started))
            return self._age

    def warm_up(self, which: tuple[str, ...]) -> None:
        for name in which:
            getattr(self, name)()


def ensure_insightface_pack(root: Path, pack: str) -> Path:
    """Download and unpack `<pack>.zip` from the InsightFace model zoo into `root/models/<pack>`.

    The zips sometimes nest a folder of the same name; the `.onnx` files are flattened so the
    directory holds them directly.
    """
    models_dir = root / "models"
    pack_dir = models_dir / pack
    if any(pack_dir.glob("*.onnx")):
        return pack_dir
    models_dir.mkdir(parents=True, exist_ok=True)
    zip_path = models_dir / f"{pack}.zip"
    if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
        import urllib.request

        url = f"{INSIGHTFACE_RELEASE}{pack}.zip"
        log.info("models.download", url=url, dest=str(zip_path))
        tmp = zip_path.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=600) as resp, tmp.open("wb") as fh:
            while chunk := resp.read(1 << 20):
                fh.write(chunk)
        tmp.replace(zip_path)
    pack_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".onnx"):
                continue
            target = pack_dir / Path(info.filename).name
            with zf.open(info) as src, target.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
    if not any(pack_dir.glob("*.onnx")):
        raise RuntimeError(f"{zip_path} contains no .onnx files")
    return pack_dir


_hub: ModelHub | None = None
_hub_lock = threading.Lock()


def get_hub(settings: Settings) -> ModelHub:
    """The process-wide hub (one set of models per worker process)."""
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = ModelHub(settings)
        return _hub


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
