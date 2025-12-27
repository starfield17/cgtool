"""
cgtool/match.py
Background/Diff matching logic
- Rule matching (RuleMatcher)
- Auto detection (AutoMatcher) - migrated from auto_match.py
"""

import os
import re
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
from PIL import Image
from scipy import ndimage

from .types import ImgInfo, PairJob, MatchMode

# ============================================================================
# Configuration constants
# ============================================================================

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Black/white thresholds
BLACK_T = 8       # <= BLACK_T treated as black
WHITE_T = 247     # >= WHITE_T treated as white

# Diff discrimination thresholds
VALID_RATIO_DIFF_TH = 0.55
MAX_FILL_CC_RATIO_DIFF_TH = 0.35

# Quantize dominant color
DOMINANT_QUANT = 16  # 16 levels per channel

# ============================================================================
# Filename parsing (migrated from auto_match.py)
# ============================================================================

# Support full-width separator ／ and half-width / \
DIFF_RE = re.compile(r"(.*?)(?:[\\/／])?差分\s*([0-９０-９]+)\s*$")


def normalize_digits(s: str) -> str:
    """Convert full-width digits to half-width"""
    trans = str.maketrans("０１２３４５６７８９", "0123456789")
    return s.translate(trans)


def split_name_no_ext(filename: str) -> str:
    """Get filename without extension"""
    return os.path.splitext(os.path.basename(filename))[0]


def parse_name(name_no_ext: str) -> Tuple[str, Optional[int], bool]:
    """
    Parse filename and extract group information
    
    Returns:
        group_key: Text before "差分N" (used for grouping)
        diff_index: Diff index (if any)
        has_diff_word: Whether it contains "差分" keyword
    """
    s = normalize_digits(name_no_ext).strip()
    m = DIFF_RE.match(s)
    if m:
        prefix = m.group(1).rstrip(" /\\／")
        idx = int(m.group(2))
        return prefix if prefix else s, idx, True
    # No "差分N", check if contains "差分"
    return s, None, ("差分" in s)


# ============================================================================
# Image feature computation (migrated from auto_match.py, optimized using scipy)
# ============================================================================

def load_rgb(path: Path, max_side: int = 1200) -> np.ndarray:
    """
    Load image as RGB uint8 array
    Optional scaling for faster feature computation
    """
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
    return np.array(img, dtype=np.uint8)


def compute_connected_component_max_ratio(mask: np.ndarray) -> float:
    """
    Compute maximum connected component ratio
    Use scipy.ndimage.label for speedup (replacing pure Python BFS)
    
    Args:
        mask: HxW boolean array
    
    Returns:
        Maximum connected component area / total area
    """
    if mask.dtype != np.bool_:
        mask = mask.astype(bool)
    
    h, w = mask.shape
    total = h * w
    if total == 0 or not mask.any():
        return 0.0
    
    # Use scipy.ndimage.label for connected component labeling
    labeled, num_features = ndimage.label(mask)
    if num_features == 0:
        return 0.0
    
    # Count size of each connected component
    component_sizes = ndimage.sum(mask, labeled, range(1, num_features + 1))
    max_cc = np.max(component_sizes) if len(component_sizes) > 0 else 0
    
    return float(max_cc) / float(total)


def dominant_color_mask(rgb: np.ndarray, quant: int = DOMINANT_QUANT) -> Tuple[np.ndarray, float]:
    """
    Find dominant color (most frequent after quantization), return its mask and ratio
    """
    # Quantize
    q = (rgb // (256 // quant)).astype(np.uint8)  # 0..quant-1
    # Pack into single integer
    packed = (q[..., 0].astype(np.int32) << 16) | (q[..., 1].astype(np.int32) << 8) | q[..., 2].astype(np.int32)
    vals, counts = np.unique(packed.ravel(), return_counts=True)
    i = int(np.argmax(counts))
    dom = vals[i]
    ratio = counts[i] / float(packed.size)
    mask = (packed == dom)
    return mask, ratio


def compute_features(path: Path) -> Tuple[int, int, float, float, float]:
    """
    Compute image features
    
    Returns:
        (w, h, valid_ratio, max_fill_cc_ratio, fill_mode_ratio)
    """
    rgb = load_rgb(path)
    h, w = rgb.shape[:2]

    # Convert to grayscale
    gray = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.uint8)

    black_mask = gray <= BLACK_T
    white_mask = gray >= WHITE_T

    # Dominant color candidates
    dom_mask, dom_ratio = dominant_color_mask(rgb)

    # Take maximum ratio among three "fill color" candidates
    black_ratio = black_mask.mean()
    white_ratio = white_mask.mean()
    fill_mode_ratio = float(max(black_ratio, white_ratio, dom_ratio))

    # Determine fill color mask
    if max(black_ratio, white_ratio) >= 0.25:
        fill_mask = black_mask if black_ratio >= white_ratio else white_mask
    else:
        fill_mask = dom_mask

    # Downsample before computing connected component (for speedup)
    ds = 2
    fill_mask_ds = fill_mask[::ds, ::ds]
    max_fill_cc_ratio = compute_connected_component_max_ratio(fill_mask_ds)

    # Valid pixels: non-black and non-white
    valid_mask = ~(black_mask | white_mask)
    valid_ratio = float(valid_mask.mean())

    return w, h, valid_ratio, float(max_fill_cc_ratio), fill_mode_ratio


def decide_diff(valid_ratio: float, max_fill_cc_ratio: float) -> Tuple[bool, float, float]:
    """
    Determine if it's a diff image
    
    Returns:
        (is_diff, diff_score, full_score)
    """
    # Diff tendency = large fill connected component + few valid pixels
    diff_score = 0.55 * max_fill_cc_ratio + 0.45 * (1.0 - valid_ratio)
    full_score = 1.0 - diff_score

    is_diff = (valid_ratio < VALID_RATIO_DIFF_TH) and (max_fill_cc_ratio > MAX_FILL_CC_RATIO_DIFF_TH)
    return is_diff, float(diff_score), float(full_score)


# ============================================================================
# Scan and pairing logic (migrated from auto_match.py)
# ============================================================================

def scan_images(folder: Path, recursive: bool = False) -> List[ImgInfo]:
    """
    Scan folder for images and compute features
    
    Args:
        folder: Input folder
        recursive: Whether to recursively scan subdirectories
    
    Returns:
        List of ImgInfo
    """
    infos: List[ImgInfo] = []
    
    if recursive:
        paths = list(folder.rglob("*"))
    else:
        paths = list(folder.iterdir())
    
    for p in paths:
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in IMAGE_EXTS:
            continue
        
        try:
            name_no_ext = split_name_no_ext(p.name)
            group_key, diff_index, has_diff_word = parse_name(name_no_ext)
            
            w, h, valid_ratio, max_fill_cc_ratio, fill_mode_ratio = compute_features(p)
            is_diff, diff_score, full_score = decide_diff(valid_ratio, max_fill_cc_ratio)
            
            infos.append(
                ImgInfo(
                    path=p,
                    filename=p.name,
                    group_key=group_key,
                    diff_index=diff_index,
                    has_diff_word=has_diff_word,
                    w=w,
                    h=h,
                    valid_ratio=valid_ratio,
                    max_fill_cc_ratio=max_fill_cc_ratio,
                    fill_mode_ratio=fill_mode_ratio,
                    is_diff=is_diff,
                    diff_score=diff_score,
                    full_score=full_score,
                )
            )
        except Exception as e:
            # Skip on read failure, logging can be added later
            continue
    
    return infos


def pick_parent_for_diff(diff: ImgInfo, candidates_full: List[ImgInfo]) -> Optional[ImgInfo]:
    """
    Select best base image for diff image
    Priority: same size, and closest with index < diff.index
    Fallback: highest full_score
    """
    # Priority: same size
    same_size = [c for c in candidates_full if c.w == diff.w and c.h == diff.h]
    pool = same_size if same_size else candidates_full
    if not pool:
        return None

    if diff.diff_index is not None:
        # Find candidates with index < diff.index, get closest
        lower = [c for c in pool if (c.diff_index is not None and c.diff_index < diff.diff_index)]
        if lower:
            return max(lower, key=lambda x: x.diff_index)
        # No index, find those without index
        no_idx = [c for c in pool if c.diff_index is None]
        if no_idx:
            return max(no_idx, key=lambda x: x.full_score)

    # Fallback: highest full_score
    return max(pool, key=lambda x: x.full_score)


def build_pairs_from_infos(infos: List[ImgInfo]) -> Dict[str, List[ImgInfo]]:
    """
    Build pairing relationships from ImgInfo list
    
    Returns:
        parent_filename -> [diff ImgInfo list]
    """
    # Group by group_key
    by_group: Dict[str, List[ImgInfo]] = {}
    for it in infos:
        by_group.setdefault(it.group_key, []).append(it)

    parent_to_children: Dict[str, List[ImgInfo]] = {}

    for gk, items in by_group.items():
        # Separate base and diff
        fulls = [x for x in items if not x.is_diff]
        diffs = [x for x in items if x.is_diff]

        # If no base but there are images, use highest full_score as base
        if not fulls and items:
            best = max(items, key=lambda x: x.full_score)
            fulls = [best]
            diffs = [x for x in items if x is not best and x.is_diff]

        # Sort diffs by index
        diffs_sorted = sorted(
            diffs,
            key=lambda x: (x.diff_index is None, x.diff_index if x.diff_index is not None else 10**9, x.filename)
        )

        for d in diffs_sorted:
            p = pick_parent_for_diff(d, fulls)
            if p is None:
                continue
            parent_to_children.setdefault(p.filename, []).append(d)

        # Sort children under each parent by index
        for pfn, children in parent_to_children.items():
            def extract_idx(info: ImgInfo) -> int:
                return info.diff_index if info.diff_index is not None else 10**9
            children.sort(key=lambda x: (extract_idx(x), x.filename))

    return parent_to_children


# ============================================================================
# AutoMatcher: Auto matching
# ============================================================================

class AutoMatcher:
    """
    Auto matcher
    Automatically pair base and diff based on filename rules and image features
    """
    
    def __init__(self, input_root: Path, recursive: bool = False):
        self.input_root = input_root
        self.recursive = recursive
        self.infos: List[ImgInfo] = []
        self._filename_to_info: Dict[str, ImgInfo] = {}
    
    def scan(self) -> None:
        """Scan and compute features"""
        self.infos = scan_images(self.input_root, self.recursive)
        self._filename_to_info = {info.filename: info for info in self.infos}
    
    def match(self) -> List[PairJob]:
        """
        Execute matching and return PairJob list
        """
        if not self.infos:
            self.scan()
        
        pairs = build_pairs_from_infos(self.infos)
        jobs: List[PairJob] = []
        
        for parent_fn, diff_infos in pairs.items():
            parent_info = self._filename_to_info.get(parent_fn)
            if parent_info is None:
                continue
            
            for diff_info in diff_infos:
                # Compute output path: maintain diff's path structure relative to input_root
                try:
                    output_rel = diff_info.path.relative_to(self.input_root)
                except ValueError:
                    output_rel = Path(diff_info.filename)
                
                jobs.append(
                    PairJob(
                        base_path=parent_info.path,
                        diff_path=diff_info.path,
                        output_rel_path=output_rel,
                        match_source=MatchMode.AUTO,
                        base_info=parent_info,
                        diff_info=diff_info,
                    )
                )
        
        return jobs


# ============================================================================
# RuleMatcher: Rule matching
# ============================================================================

class RuleMatcher:
    """
    Rule matcher
    User specifies naming rules, for example:
      base_pattern: "{name}.png"
      diff_pattern: "{name}/diff*.png"
    """
    
    def __init__(
        self,
        input_root: Path,
        base_pattern: str = "*.png",
        diff_pattern: str = "*/diff*.png",
        recursive: bool = False,
    ):
        self.input_root = input_root
        self.base_pattern = base_pattern
        self.diff_pattern = diff_pattern
        self.recursive = recursive
    
    def match(self) -> List[PairJob]:
        """
        Execute rule matching
        """
        jobs: List[PairJob] = []
        
        # Collect all images
        if self.recursive:
            all_images = list(self.input_root.rglob("*"))
        else:
            all_images = list(self.input_root.iterdir())
        
        all_images = [p for p in all_images if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        
        # Find base files (not in subdirectory, or matching base_pattern)
        bases: List[Path] = []
        for p in all_images:
            rel = p.relative_to(self.input_root)
            # Simple check: if filename matches base_pattern
            if fnmatch.fnmatch(p.name, self.base_pattern.replace("{name}", "*")):
                # Exclude diff
                if "差分" not in p.name:
                    bases.append(p)
        
        # For each base, find corresponding diff
        for base_path in bases:
            base_name = split_name_no_ext(base_path.name)
            
            # Construct diff glob pattern
            diff_glob = self.diff_pattern.replace("{name}", base_name)
            
            # Find matching diff
            diff_paths = list(self.input_root.glob(diff_glob))
            diff_paths = [p for p in diff_paths if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
            
            for diff_path in diff_paths:
                try:
                    output_rel = diff_path.relative_to(self.input_root)
                except ValueError:
                    output_rel = Path(diff_path.name)
                
                jobs.append(
                    PairJob(
                        base_path=base_path,
                        diff_path=diff_path,
                        output_rel_path=output_rel,
                        match_source=MatchMode.RULE,
                    )
                )
        
        return jobs


# ============================================================================
# Unified entry point
# ============================================================================

def match_auto(input_root: Path, recursive: bool = False) -> List[PairJob]:
    """Auto matching entry point"""
    matcher = AutoMatcher(input_root, recursive)
    return matcher.match()


def match_rule(
    input_root: Path,
    base_pattern: str = "*.png",
    diff_pattern: str = "*/diff*.png",
    recursive: bool = False,
) -> List[PairJob]:
    """Rule matching entry point"""
    matcher = RuleMatcher(input_root, base_pattern, diff_pattern, recursive)
    return matcher.match()
