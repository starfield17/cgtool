"""
cgtool/imageops.py
Image operation module:
- Background color detection and removal (bgremove)
- Multi-resolution alignment algorithm (align) - migrated from C# AutoCGAligner
- Image composition (compose)

Performance optimization: prefer Numba JIT, fallback to pure NumPy when unavailable
"""

import numpy as np
from PIL import Image
from pathlib import Path
from typing import Tuple, Optional

# Numba is an optional dependency
try:
    from numba import jit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    # Define empty decorator
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator
    prange = range

from .cgtypes import AlignParams, AlignResult, BgColor

# ============================================================================
# Constants
# ============================================================================

MAX_PIXEL_DIS = 255 * 255 * 3  # Maximum RGB vector distance


# ============================================================================
# Background color detection and removal (bgremove)
# ============================================================================

def load_rgba(path: Path) -> np.ndarray:
    """Load image as RGBA uint8 array (H, W, 4)"""
    img = Image.open(path).convert("RGBA")
    return np.array(img, dtype=np.uint8)


def save_rgba(arr: np.ndarray, path: Path) -> None:
    """Save RGBA array as PNG"""
    img = Image.fromarray(arr, mode="RGBA")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def detect_bg_color(rgba: np.ndarray) -> Tuple[BgColor, Tuple[int, int, int]]:
    """
    Auto-detect background color
    Strategy: count most frequent color, determine if black, white, or other
    
    Returns:
        (BgColor type, (R, G, B) value)
    """
    rgb = rgba[..., :3]
    alpha = rgba[..., 3]
    
    # Only look at opaque pixels
    opaque_mask = alpha > 0
    if not opaque_mask.any():
        return BgColor.BLACK, (0, 0, 0)
    
    rgb_opaque = rgb[opaque_mask]
    
    # Quantize and count (for speedup)
    quant = 8  # Coarse quantization
    q = (rgb_opaque // (256 // quant)).astype(np.uint8)
    packed = (q[..., 0].astype(np.int32) << 16) | (q[..., 1].astype(np.int32) << 8) | q[..., 2].astype(np.int32)
    vals, counts = np.unique(packed, return_counts=True)
    
    dom_idx = np.argmax(counts)
    dom_packed = vals[dom_idx]
    
    # Restore RGB
    r = ((dom_packed >> 16) & 0xFF) * (256 // quant) + (256 // quant) // 2
    g = ((dom_packed >> 8) & 0xFF) * (256 // quant) + (256 // quant) // 2
    b = (dom_packed & 0xFF) * (256 // quant) + (256 // quant) // 2
    
    # Determine black/white/other
    brightness = 0.299 * r + 0.587 * g + 0.114 * b
    if brightness < 30:
        return BgColor.BLACK, (r, g, b)
    elif brightness > 225:
        return BgColor.WHITE, (r, g, b)
    else:
        return BgColor.CUSTOM, (r, g, b)


@jit(nopython=True, parallel=True, cache=True)
def _clear_color_match(
    rgba: np.ndarray,
    target_r: int,
    target_g: int,
    target_b: int,
    tolerance_sq: int,
) -> np.ndarray:
    """
    Clear pixels close to target color (set to transparent)
    match-to-color mode: compare distance with specified background color
    
    Accelerated with Numba
    """
    h, w = rgba.shape[:2]
    result = rgba.copy()
    
    for y in prange(h):
        for x in range(w):
            r = int(rgba[y, x, 0])
            g = int(rgba[y, x, 1])
            b = int(rgba[y, x, 2])
            
            dr = r - target_r
            dg = g - target_g
            db = b - target_b
            dist_sq = dr * dr + dg * dg + db * db
            
            if dist_sq <= tolerance_sq:
                result[y, x, 0] = 0
                result[y, x, 1] = 0
                result[y, x, 2] = 0
                result[y, x, 3] = 0
    
    return result


@jit(nopython=True, parallel=True, cache=True)
def _clear_color_norm(
    rgba: np.ndarray,
    threshold_sq: int,
) -> np.ndarray:
    """
    Clear dark pixels (RGB vector length below threshold)
    norm-threshold mode: compatible with original C# ClearColor behavior
    
    Original C# code: if (r*r + b*b + g*g < distance) -> transparent
    """
    h, w = rgba.shape[:2]
    result = rgba.copy()
    
    for y in prange(h):
        for x in range(w):
            r = int(rgba[y, x, 0])
            g = int(rgba[y, x, 1])
            b = int(rgba[y, x, 2])
            
            norm_sq = r * r + g * g + b * b
            
            if norm_sq < threshold_sq:
                result[y, x, 0] = 0
                result[y, x, 1] = 0
                result[y, x, 2] = 0
                result[y, x, 3] = 0
    
    return result


def clear_color(
    rgba: np.ndarray,
    bg_color: Tuple[int, int, int] = (0, 0, 0),
    tolerance: int = 30,
    mode: str = "match",
) -> np.ndarray:
    """
    Background color removal
    
    Args:
        rgba: RGBA image array
        bg_color: Target background color (R, G, B)
        tolerance: Tolerance (0-255)
        mode: "match" = compare with specified color, "norm" = by RGB vector length
    
    Returns:
        Processed RGBA array
    """
    if mode == "match":
        tolerance_sq = tolerance * tolerance * 3  # Three-channel distance
        return _clear_color_match(rgba, bg_color[0], bg_color[1], bg_color[2], tolerance_sq)
    else:
        # norm mode: tolerance directly as threshold (similar to original C# distance parameter)
        threshold_sq = tolerance * tolerance * 3
        return _clear_color_norm(rgba, threshold_sq)


# ============================================================================
# Edge extraction (GetBorder) - migrated from C#
# ============================================================================

@jit(nopython=True, cache=True)
def _get_border_impl(rgba: np.ndarray) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Extract image edge pixels
    Edge definition: non-transparent pixel with at least one adjacent transparent pixel
    
    Returns:
        border_coords: Nx2 int32 (y, x)
        border_rgb: Nx3 uint8
        npixels: Number of edge pixels
    """
    h, w = rgba.shape[:2]
    
    # First count edge pixels
    count = 0
    for y in range(h):
        for x in range(w):
            a = rgba[y, x, 3]
            if a == 0:
                continue
            
            # Check if four neighbors have transparent pixel
            is_edge = False
            if x > 0 and rgba[y, x - 1, 3] == 0:
                is_edge = True
            elif x < w - 1 and rgba[y, x + 1, 3] == 0:
                is_edge = True
            elif y > 0 and rgba[y - 1, x, 3] == 0:
                is_edge = True
            elif y < h - 1 and rgba[y + 1, x, 3] == 0:
                is_edge = True
            # Border also counts as edge
            elif x == 0 or x == w - 1 or y == 0 or y == h - 1:
                is_edge = True
            
            if is_edge:
                count += 1
    
    # Allocate arrays
    border_coords = np.zeros((count, 2), dtype=np.int32)
    border_rgb = np.zeros((count, 3), dtype=np.uint8)
    
    # Fill
    idx = 0
    for y in range(h):
        for x in range(w):
            a = rgba[y, x, 3]
            if a == 0:
                continue
            
            is_edge = False
            if x > 0 and rgba[y, x - 1, 3] == 0:
                is_edge = True
            elif x < w - 1 and rgba[y, x + 1, 3] == 0:
                is_edge = True
            elif y > 0 and rgba[y - 1, x, 3] == 0:
                is_edge = True
            elif y < h - 1 and rgba[y + 1, x, 3] == 0:
                is_edge = True
            elif x == 0 or x == w - 1 or y == 0 or y == h - 1:
                is_edge = True
            
            if is_edge:
                border_coords[idx, 0] = y
                border_coords[idx, 1] = x
                border_rgb[idx, 0] = rgba[y, x, 0]
                border_rgb[idx, 1] = rgba[y, x, 1]
                border_rgb[idx, 2] = rgba[y, x, 2]
                idx += 1
    
    return border_coords, border_rgb, count


def get_border(rgba: np.ndarray) -> Tuple[np.ndarray, np.ndarray, int]:
    """
    Extract edge pixels
    
    Returns:
        border_coords: Nx2 array (y, x)
        border_rgb: Nx3 array (R, G, B)
        npixels: Number of edge pixels
    """
    return _get_border_impl(rgba)


# ============================================================================
# Alignment algorithm (AlignImage) - migrated from C#
# ============================================================================

@jit(nopython=True, cache=True)
def _compute_distance_at(
    base_rgb: np.ndarray,  # H×W×3
    border_coords: np.ndarray,  # N×2 (y, x)
    border_rgb: np.ndarray,  # N×3
    dx: int,
    dy: int,
    min_dis: int,
) -> int:
    """
    Calculate total distance when diff edge is offset by (dx, dy) on base
    Supports early termination: return immediately if exceeding min_dis
    """
    n = border_coords.shape[0]
    dis = 0
    
    for i in range(n):
        by = border_coords[i, 0] + dy
        bx = border_coords[i, 1] + dx
        
        # Boundary check
        if by < 0 or by >= base_rgb.shape[0] or bx < 0 or bx >= base_rgb.shape[1]:
            dis += MAX_PIXEL_DIS
        else:
            dr = int(base_rgb[by, bx, 0]) - int(border_rgb[i, 0])
            dg = int(base_rgb[by, bx, 1]) - int(border_rgb[i, 1])
            db = int(base_rgb[by, bx, 2]) - int(border_rgb[i, 2])
            dis += dr * dr + dg * dg + db * db
        
        # Early termination
        if dis >= min_dis:
            return dis
    
    return dis


@jit(nopython=True, cache=True)
def _align_range(
    base_rgb: np.ndarray,
    border_coords: np.ndarray,
    border_rgb: np.ndarray,
    x_start: int,
    x_end: int,
    x_step: int,
    y_start: int,
    y_end: int,
    y_step: int,
    min_dis: int,
    best_x: int,
    best_y: int,
) -> Tuple[int, int, int]:
    """
    Search for best alignment position in specified range
    """
    for dx in range(x_start, x_end + 1, x_step):
        for dy in range(y_start, y_end + 1, y_step):
            dis = _compute_distance_at(base_rgb, border_coords, border_rgb, dx, dy, min_dis)
            if dis < min_dis:
                min_dis = dis
                best_x = dx
                best_y = dy
    
    return min_dis, best_x, best_y


def align_image(
    base_rgba: np.ndarray,
    diff_rgba: np.ndarray,
    params: Optional[AlignParams] = None,
) -> AlignResult:
    """
    Multi-resolution image alignment
    
    Migrated from C# AlignImage(), strategy:
    1. Initial large step (e.g., 20), quickly traverse full range
    2. After finding best position, shrink range to ±step*ext_scale
    3. Gradually shrink step until step is 1
    
    Args:
        base_rgba: Base image RGBA (H, W, 4)
        diff_rgba: Diff image RGBA (h, w, 4)
        params: Alignment parameters
    
    Returns:
        AlignResult
    """
    if params is None:
        params = AlignParams.fast()
    
    base_rgb = base_rgba[..., :3].copy()
    
    # Extract diff edge
    border_coords, border_rgb, npixels = get_border(diff_rgba)
    
    if npixels == 0:
        return AlignResult(dx=0, dy=0, distance=0, fit_percent=100.0, npixels=0)
    
    base_h, base_w = base_rgba.shape[:2]
    diff_h, diff_w = diff_rgba.shape[:2]
    
    # Search range
    x_range = base_w - diff_w
    y_range = base_h - diff_h
    
    if x_range < 0 or y_range < 0:
        # Diff larger than base, cannot align
        return AlignResult(dx=0, dy=0, distance=MAX_PIXEL_DIS * npixels, fit_percent=0.0, npixels=npixels)
    
    x_start, x_end = 0, x_range
    y_start, y_end = 0, y_range
    
    # Initial step
    x_step = min((x_end - x_start) // params.step_divisor, params.init_step)
    y_step = min((y_end - y_start) // params.step_divisor, params.init_step)
    if x_step == 0:
        x_step = 1
    if y_step == 0:
        y_step = 1
    
    min_dis = MAX_PIXEL_DIS * npixels
    best_x, best_y = 0, 0
    
    x_flag = True
    y_flag = True
    
    # Multiple rounds of iteration
    while x_flag or y_flag:
        min_dis, best_x, best_y = _align_range(
            base_rgb, border_coords, border_rgb,
            x_start, x_end, x_step,
            y_start, y_end, y_step,
            min_dis, best_x, best_y,
        )
        
        # Shrink range
        x_start = max(best_x - x_step * params.ext_scale, 0)
        x_end = min(best_x + x_step * params.ext_scale, x_range)
        y_start = max(best_y - y_step * params.ext_scale, 0)
        y_end = min(best_y + y_step * params.ext_scale, y_range)
        
        # Shrink step
        if x_step == 1:
            x_flag = False
        if x_flag:
            x_step = (x_end - x_start) // params.step_divisor
            if x_step == 0:
                x_step = 1
        
        if y_step == 1:
            y_flag = False
        if y_flag:
            y_step = (y_end - y_start) // params.step_divisor
            if y_step == 0:
                y_step = 1
    
    # Calculate match rate
    fit_percent = get_fit(min_dis, npixels)
    
    return AlignResult(
        dx=best_x,
        dy=best_y,
        distance=min_dis,
        fit_percent=fit_percent,
        npixels=npixels,
    )


def get_fit(distance: int, npixels: int) -> float:
    """
    Calculate match rate percentage based on distance
    Migrated from C# GetFit()
    """
    if npixels == 0:
        return 100.0
    normalized = distance / npixels / MAX_PIXEL_DIS
    return (1.0 - np.sqrt(normalized)) * 100.0


# ============================================================================
# Image composition (compose)
# ============================================================================

def compose_aligned(
    base_rgba: np.ndarray,
    diff_rgba: np.ndarray,
    dx: int,
    dy: int,
) -> np.ndarray:
    """
    Compose diff image onto base image
    
    Args:
        base_rgba: Base image RGBA
        diff_rgba: Diff image RGBA (background removed)
        dx, dy: Alignment offset
    
    Returns:
        Composed RGBA image
    """
    result = base_rgba.copy()
    diff_h, diff_w = diff_rgba.shape[:2]
    
    # Safe boundaries
    y1 = max(0, dy)
    y2 = min(result.shape[0], dy + diff_h)
    x1 = max(0, dx)
    x2 = min(result.shape[1], dx + diff_w)
    
    sy1 = y1 - dy
    sy2 = sy1 + (y2 - y1)
    sx1 = x1 - dx
    sx2 = sx1 + (x2 - x1)
    
    if y2 <= y1 or x2 <= x1:
        return result
    
    # Alpha blending
    diff_region = diff_rgba[sy1:sy2, sx1:sx2]
    base_region = result[y1:y2, x1:x2]
    
    alpha = diff_region[..., 3:4].astype(np.float32) / 255.0
    
    # Foreground overwrites background
    blended = alpha * diff_region[..., :3].astype(np.float32) + (1 - alpha) * base_region[..., :3].astype(np.float32)
    result[y1:y2, x1:x2, :3] = blended.astype(np.uint8)
    
    # Alpha channel merge
    result_alpha = base_region[..., 3:4].astype(np.float32) / 255.0
    combined_alpha = alpha + result_alpha * (1 - alpha)
    result[y1:y2, x1:x2, 3:4] = (combined_alpha * 255).astype(np.uint8)
    
    return result


# ============================================================================
# Convenience functions
# ============================================================================

def process_single(
    base_path: Path,
    diff_path: Path,
    output_path: Path,
    bg_color: Optional[Tuple[int, int, int]] = None,
    tolerance: int = 30,
    align_params: Optional[AlignParams] = None,
    bg_mode: str = "match",
) -> AlignResult:
    """
    Process single pair job
    
    Args:
        base_path: Base image path
        diff_path: Diff image path
        output_path: Output path
        bg_color: Background color (R, G, B), None means auto-detect
        tolerance: Background removal tolerance
        align_params: Alignment parameters
        bg_mode: Background removal mode "match" or "norm"
    
    Returns:
        AlignResult
    """
    # Load images
    base_rgba = load_rgba(base_path)
    diff_rgba = load_rgba(diff_path)
    
    # Detect/remove background
    if bg_color is None:
        _, detected_color = detect_bg_color(diff_rgba)
        bg_color = detected_color
    
    diff_rgba = clear_color(diff_rgba, bg_color, tolerance, bg_mode)
    
    # Align
    result = align_image(base_rgba, diff_rgba, align_params)
    
    # Compose and save
    output = compose_aligned(base_rgba, diff_rgba, result.dx, result.dy)
    save_rgba(output, output_path)
    
    return result
