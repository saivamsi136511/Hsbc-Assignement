"""
image_processor.py
==================
Core OpenCV-based image analysis engine for visual regression testing.

Performs multi-layer comparison between a baseline and a new deployment
screenshot, going well beyond pixel-by-pixel diffing to detect structural
layout shifts, missing UI elements, and meaningful visual regressions while
reducing false positives from dynamic content (timestamps, ads, animations).

Comparison Layers
-----------------
1. SSIM  — structural similarity index; overall quality score
2. Feature matching (ORB) — detects spatial layout shifts between frames
3. Canny edge detection — finds missing / moved structural elements
4. Contour analysis — groups changed pixels into meaningful bounding regions
5. Histogram comparison — detects colour palette / style-sheet regressions

Usage (standalone)
------------------
    from image_processor import ImageProcessor, ComparisonResult
    proc = ImageProcessor(ssim_threshold=0.95, min_change_area=100)
    result = proc.compare("baseline.png", "current.png")
    print(result.ssim_score, result.changed_regions)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

try:
    from skimage.metrics import structural_similarity as ssim
    _SKIMAGE_AVAILABLE = True
except ImportError:
    _SKIMAGE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ChangeRegion:
    """A rectangular area where a visual difference was detected."""
    x: int
    y: int
    width: int
    height: int
    area: int
    severity: str = "medium"   # "low" | "medium" | "high"
    description: str = ""

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class ComparisonResult:
    """Full result of comparing two screenshots."""
    ssim_score: float = 1.0
    passed: bool = True
    total_changed_pixels: int = 0
    changed_percentage: float = 0.0
    changed_regions: List[ChangeRegion] = field(default_factory=list)
    layout_shift_detected: bool = False
    feature_match_score: float = 1.0
    edge_diff_score: float = 0.0
    histogram_similarity: float = 1.0
    diff_image: Optional[np.ndarray] = None       # uint8 grayscale diff
    heatmap_image: Optional[np.ndarray] = None    # BGR colour heatmap
    annotated_image: Optional[np.ndarray] = None  # baseline + overlaid boxes
    error: Optional[str] = None

    @property
    def severity(self) -> str:
        if self.ssim_score >= 0.98:
            return "low"
        if self.ssim_score >= 0.90:
            return "medium"
        return "high"


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

class ImageProcessor:
    """
    Compares two screenshots using multiple OpenCV / scikit-image techniques.

    Parameters
    ----------
    ssim_threshold : float
        SSIM score below which the comparison is treated as a failure (0–1).
    min_change_area : int
        Minimum pixel area for a contour to be reported as a changed region.
        Smaller blobs are treated as noise / anti-aliasing artefacts.
    ignore_regions : list of (x, y, w, h) tuples
        Pixel rectangles to black-out before comparison (dynamic content zones:
        clocks, carousels, ads …).
    blur_before_diff : bool
        Apply a small Gaussian blur before diffing to further reduce
        sub-pixel / aliasing false positives.
    """

    def __init__(
        self,
        ssim_threshold: float = 0.95,
        min_change_area: int = 100,
        ignore_regions: Optional[List[Tuple[int, int, int, int]]] = None,
        blur_before_diff: bool = True,
    ):
        self.ssim_threshold = ssim_threshold
        self.min_change_area = min_change_area
        self.ignore_regions = ignore_regions or []
        self.blur_before_diff = blur_before_diff

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(self, baseline_path: str, current_path: str) -> ComparisonResult:
        """
        Full multi-layer comparison between baseline and current screenshots.

        Returns a ComparisonResult with SSIM score, changed regions,
        diff/heatmap images ready for the reporter, and a pass/fail flag.
        """
        try:
            baseline_bgr = self._load(baseline_path)
            current_bgr  = self._load(current_path)
        except (FileNotFoundError, cv2.error) as exc:
            return ComparisonResult(error=str(exc))

        # Resize current to match baseline if sizes differ
        if baseline_bgr.shape != current_bgr.shape:
            current_bgr = cv2.resize(
                current_bgr,
                (baseline_bgr.shape[1], baseline_bgr.shape[0]),
                interpolation=cv2.INTER_AREA,
            )

        # Mask dynamic content zones
        baseline_bgr = self._apply_ignore_regions(baseline_bgr)
        current_bgr  = self._apply_ignore_regions(current_bgr)

        # Convert to grayscale for structural analysis
        base_gray = cv2.cvtColor(baseline_bgr, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(current_bgr,  cv2.COLOR_BGR2GRAY)

        if self.blur_before_diff:
            base_gray = cv2.GaussianBlur(base_gray, (3, 3), 0)
            curr_gray = cv2.GaussianBlur(curr_gray, (3, 3), 0)

        result = ComparisonResult()

        # Layer 1: SSIM
        result.ssim_score = self._compute_ssim(base_gray, curr_gray)

        # Layer 2: pixel diff + contours
        diff, result.total_changed_pixels, result.changed_percentage = \
            self._pixel_diff(base_gray, curr_gray, baseline_bgr.shape)
        result.diff_image = diff
        result.changed_regions = self._find_changed_regions(diff, baseline_bgr, current_bgr)

        # Layer 3: feature matching (ORB) for layout-shift detection
        result.feature_match_score, result.layout_shift_detected = \
            self._feature_match(base_gray, curr_gray)

        # Layer 4: edge diff score
        result.edge_diff_score = self._edge_diff_score(base_gray, curr_gray)

        # Layer 5: histogram similarity
        result.histogram_similarity = self._histogram_similarity(baseline_bgr, current_bgr)

        # Build visualisations
        result.heatmap_image   = self._build_heatmap(diff)
        result.annotated_image = self._build_annotated(baseline_bgr, current_bgr, result.changed_regions)

        # Pass / fail
        result.passed = result.ssim_score >= self.ssim_threshold

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: str) -> np.ndarray:
        img = cv2.imread(path)
        if img is None:
            raise FileNotFoundError(f"Could not read image: {path!r}")
        return img

    def _apply_ignore_regions(self, img: np.ndarray) -> np.ndarray:
        out = img.copy()
        for (x, y, w, h) in self.ignore_regions:
            out[y : y + h, x : x + w] = 0
        return out

    @staticmethod
    def _compute_ssim(gray1: np.ndarray, gray2: np.ndarray) -> float:
        if _SKIMAGE_AVAILABLE:
            score, _ = ssim(gray1, gray2, full=True)
            return float(score)
        # Fallback: normalised cross-correlation approximation
        n1 = gray1.astype(np.float32)
        n2 = gray2.astype(np.float32)
        numerator   = 2 * np.mean(n1 * n2) + 1e-6
        denominator = np.mean(n1 ** 2) + np.mean(n2 ** 2) + 1e-6
        return float(numerator / denominator)

    @staticmethod
    def _pixel_diff(
        gray1: np.ndarray,
        gray2: np.ndarray,
        original_shape: Tuple,
    ) -> Tuple[np.ndarray, int, float]:
        diff = cv2.absdiff(gray1, gray2)
        _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        total_changed = int(np.count_nonzero(thresh))
        total_pixels  = original_shape[0] * original_shape[1]
        pct = round(100.0 * total_changed / total_pixels, 2) if total_pixels else 0.0
        return diff, total_changed, pct

    def _find_changed_regions(
        self,
        diff: np.ndarray,
        baseline_bgr: np.ndarray,
        current_bgr: np.ndarray,
    ) -> List[ChangeRegion]:
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        # Dilate to merge nearby changes into coherent blobs
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        dilated = cv2.dilate(thresh, kernel, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        regions: List[ChangeRegion] = []
        for cnt in contours:
            area = int(cv2.contourArea(cnt))
            if area < self.min_change_area:
                continue   # noise filter
            x, y, w, h = cv2.boundingRect(cnt)

            # Determine severity by comparing mean pixel intensity inside ROI
            base_roi = baseline_bgr[y : y + h, x : x + w]
            curr_roi = current_bgr[y : y + h, x : x + w]
            intensity_diff = float(np.mean(np.abs(base_roi.astype(int) - curr_roi.astype(int))))

            if intensity_diff > 80:
                sev = "high"
            elif intensity_diff > 40:
                sev = "medium"
            else:
                sev = "low"

            regions.append(ChangeRegion(
                x=x, y=y, width=w, height=h,
                area=area, severity=sev,
                description=f"Changed region at ({x},{y}) size {w}×{h}px, Δintensity={intensity_diff:.1f}",
            ))

        # Sort by severity then area (largest / most critical first)
        sev_order = {"high": 0, "medium": 1, "low": 2}
        regions.sort(key=lambda r: (sev_order[r.severity], -r.area))
        return regions

    @staticmethod
    def _feature_match(gray1: np.ndarray, gray2: np.ndarray) -> Tuple[float, bool]:
        """ORB feature matching — detects spatial layout shifts."""
        orb = cv2.ORB_create(nfeatures=500)
        kp1, des1 = orb.detectAndCompute(gray1, None)
        kp2, des2 = orb.detectAndCompute(gray2, None)

        if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
            return 1.0, False

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des1, des2)
        if not matches:
            return 0.0, True

        # Good matches: distance below median
        distances = [m.distance for m in matches]
        median_dist = float(np.median(distances))
        good = [m for m in matches if m.distance < median_dist * 0.75]

        match_ratio = len(good) / len(matches)

        # Spatial displacement of matched keypoints
        shifts = []
        for m in good:
            pt1 = np.array(kp1[m.queryIdx].pt)
            pt2 = np.array(kp2[m.trainIdx].pt)
            shifts.append(np.linalg.norm(pt1 - pt2))
        mean_shift = float(np.mean(shifts)) if shifts else 0.0
        layout_shifted = mean_shift > 20.0   # >20px mean keypoint displacement

        return round(match_ratio, 4), layout_shifted

    @staticmethod
    def _edge_diff_score(gray1: np.ndarray, gray2: np.ndarray) -> float:
        """Canny edge maps differ → structural element added/removed."""
        edges1 = cv2.Canny(gray1, 50, 150)
        edges2 = cv2.Canny(gray2, 50, 150)
        diff   = cv2.absdiff(edges1, edges2)
        total  = float(edges1.size)
        return round(float(np.count_nonzero(diff)) / total, 4) if total else 0.0

    @staticmethod
    def _histogram_similarity(bgr1: np.ndarray, bgr2: np.ndarray) -> float:
        """Colour histogram correlation (1.0 = identical palette)."""
        scores = []
        for ch in range(3):
            h1 = cv2.calcHist([bgr1], [ch], None, [256], [0, 256])
            h2 = cv2.calcHist([bgr2], [ch], None, [256], [0, 256])
            cv2.normalize(h1, h1)
            cv2.normalize(h2, h2)
            scores.append(cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))
        return round(float(np.mean(scores)), 4)

    @staticmethod
    def _build_heatmap(diff: np.ndarray) -> np.ndarray:
        """Apply COLORMAP_JET to grayscale diff → vivid heatmap."""
        norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return cv2.applyColorMap(norm, cv2.COLORMAP_JET)

    @staticmethod
    def _build_annotated(
        baseline: np.ndarray,
        current: np.ndarray,
        regions: List[ChangeRegion],
    ) -> np.ndarray:
        """Side-by-side image with changed regions highlighted in red (baseline) / green (current)."""
        ann_base = baseline.copy()
        ann_curr = current.copy()

        sev_colors = {"high": (0, 0, 255), "medium": (0, 165, 255), "low": (0, 255, 0)}

        for r in regions:
            col = sev_colors.get(r.severity, (0, 255, 255))
            cv2.rectangle(ann_base, (r.x, r.y), (r.x + r.width, r.y + r.height), col, 2)
            cv2.rectangle(ann_curr, (r.x, r.y), (r.x + r.width, r.y + r.height), col, 2)
            cv2.putText(
                ann_curr, r.severity.upper(),
                (r.x + 4, r.y + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA,
            )

        divider = np.full((baseline.shape[0], 4, 3), 200, dtype=np.uint8)
        return np.hstack([ann_base, divider, ann_curr])

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def save_diff_images(
        self,
        result: ComparisonResult,
        output_dir: str,
        prefix: str = "vrt",
    ) -> dict:
        """Save diff, heatmap, and annotated images to *output_dir*."""
        os.makedirs(output_dir, exist_ok=True)
        paths = {}
        if result.heatmap_image is not None:
            p = os.path.join(output_dir, f"{prefix}_heatmap.png")
            cv2.imwrite(p, result.heatmap_image)
            paths["heatmap"] = p
        if result.annotated_image is not None:
            p = os.path.join(output_dir, f"{prefix}_annotated.png")
            cv2.imwrite(p, result.annotated_image)
            paths["annotated"] = p
        if result.diff_image is not None:
            p = os.path.join(output_dir, f"{prefix}_diff.png")
            cv2.imwrite(p, result.diff_image)
            paths["diff"] = p
        return paths
