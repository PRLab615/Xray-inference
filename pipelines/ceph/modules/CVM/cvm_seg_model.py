"""CVM Segmentation model wrapper."""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import numpy as np

import torch
from ultralytics import YOLO

from pipelines.ceph.modules.CVM.pre_post import preprocess_image
from tools.weight_fetcher import ensure_weight_file, WeightFetchError
from tools.timer import timer

logger = logging.getLogger(__name__)

@dataclass
class CVMSegResult:
    mask_coordinates: List[List[int]]
    confidence: float
    status: str = "ok"

class CVMSegModel:
    """
    Wraps Ultralytics YOLO Segmentation model.
    """

    def __init__(
        self,
        weights_path: Optional[str] = None,
        weights_key: Optional[str] = None,
        weights_force_download: bool = False,
        device: str = "0",
        conf: float = 0.25,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.weights_force_download = weights_force_download
        self.weights_key = weights_key
        self.weights_path = self._resolve_weights_path(weights_path)
        self.device = self._normalize_device(device)
        self.conf = conf

        self._model: Optional[YOLO] = None
        self._ensure_model()

    def _ensure_model(self) -> YOLO:
        if self._model is None:
            self._model = self.__init__model()
        return self._model

    def _resolve_weights_path(self, explicit_path: Optional[str]) -> str:
        # Same logic as CVMModel
        env_weights = os.getenv("CVM_SEG_MODEL_WEIGHTS")
        candidates = [
            ("explicit", explicit_path),
            ("weights_key", self.weights_key),
            ("env", env_weights),
        ]

        for origin, candidate in candidates:
            if not candidate:
                continue
            if os.path.exists(candidate):
                self.logger.info("Using local CVM Seg weights: %s", candidate)
                return candidate
            if origin in {"explicit", "weights_key"}:
                try:
                    downloaded = ensure_weight_file(candidate, force_download=self.weights_force_download)
                    return downloaded
                except WeightFetchError:
                    continue
        
        # Fallback error
        raise FileNotFoundError("CVM Seg weights not found.")

    def __init__model(self) -> YOLO:
        if not os.path.exists(self.weights_path):
            raise FileNotFoundError(f"Weights not found: {self.weights_path}")
        self.logger.info("Loading CVM Seg model: %s", self.weights_path)
        model = YOLO(self.weights_path)
        if self.device != "cpu":
            try:
                model.to(self.device)
            except Exception as e:
                self.logger.warning("Failed to move to %s: %s", self.device, e)
        return model

    def _normalize_device(self, device: Optional[str]) -> str:
        if not torch.cuda.is_available():
            return "cpu"
        if device is None:
            return "cuda:0"
        return str(device)

    def predict(self, image_path: str) -> CVMSegResult:
        with timer.record("ceph_cvm_seg.pre"):
            processed_path, img_height, img_width = preprocess_image(image_path, self.logger)

        with timer.record("ceph_cvm_seg.inference"):
            model = self._ensure_model()
            import cv2
            img = cv2.imread(processed_path)
            if img is None:
                raise ValueError(f"Cannot read image: {processed_path}")
            
            # Run inference
            results = model.predict(img, conf=self.conf, save=False, verbose=False)
        
        with timer.record("ceph_cvm_seg.post"):
            # Extract mask
            mask_coords = []
            conf = 0.0
            
            if results and results[0].masks:
                # Check boxes for confidence
                if results[0].boxes:
                    confs = results[0].boxes.conf.cpu().numpy()
                    if len(confs) > 0:
                        # Use max confidence as the representative confidence
                        conf = float(np.max(confs))
                
                # Extract XY coordinates for ALL masks
                # masks.xy returns list of np.array [[x,y], [x,y]...] in pixels
                masks_xy = results[0].masks.xy
                
                self.logger.info(f"CVM Segmentation found {len(masks_xy)} masks.")

                # Collect all polygons
                for poly in masks_xy:
                    # poly is np.array [[x,y], ...]
                    # Frontend expects list of polygons, where each polygon is [[x,y], ...]
                    mask_coords.append(poly.tolist())
            
            return CVMSegResult(mask_coordinates=mask_coords, confidence=conf)
