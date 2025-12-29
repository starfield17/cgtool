"""
cgtool - CG Image Auto Pairing, Background Removal, and Alignment Tool

Usage:
    # GUI (default if PySide6 installed)
    python -m cgtool
    
    # CLI
    cgtool process ./input -o ./output
    cgtool scan ./input
    cgtool info ./image.png
    
    # Force CLI mode
    python -m cgtool --cli process ./input -o ./output
"""

__version__ = "1.0.0"
__author__ = "starfield17"

from .cgtypes import (
    ImgInfo,
    PairJob,
    ReportItem,
    ProcessReport,
    AlignResult,
    AlignParams,
    MatchMode,
    AlignMode,
    BgColor,
    JobStatus,
    FailReason,
)

from .match import (
    match_auto,
    match_rule,
    parse_name,
    normalize_digits,
    compute_features,
    decide_diff,
    scan_images,
    build_pairs_from_infos,
    AutoMatcher,
    RuleMatcher,
)

from .imageops import (
    load_rgba,
    save_rgba,
    detect_bg_color,
    clear_color,
    get_border,
    align_image,
    compose_aligned,
    get_fit,
    process_single,
)

from .pipeline import (
    Pipeline,
    run_pipeline,
)

# Conditional GUI import
try:
    from .gui import run_gui, MainWindow
    _HAS_GUI = True
except ImportError:
    _HAS_GUI = False
    run_gui = None
    MainWindow = None


def has_gui() -> bool:
    """Check if GUI is available (PySide6 installed)"""
    return _HAS_GUI


__all__ = [
    # Version
    "__version__",
    # Types
    "ImgInfo",
    "PairJob",
    "ReportItem",
    "ProcessReport",
    "AlignResult",
    "AlignParams",
    "MatchMode",
    "AlignMode",
    "BgColor",
    "JobStatus",
    "FailReason",
    # Matching
    "match_auto",
    "match_rule",
    "parse_name",
    "normalize_digits",
    "compute_features",
    "decide_diff",
    "scan_images",
    "build_pairs_from_infos",
    "AutoMatcher",
    "RuleMatcher",
    # Image Operations
    "load_rgba",
    "save_rgba",
    "detect_bg_color",
    "clear_color",
    "get_border",
    "align_image",
    "compose_aligned",
    "get_fit",
    "process_single",
    # Pipeline
    "Pipeline",
    "run_pipeline",
    # GUI
    "has_gui",
    "run_gui",
    "MainWindow",
]
