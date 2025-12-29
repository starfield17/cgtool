"""
cgtool/cgtypes.py
Data structure definitions: ImgInfo, PairJob, ReportItem, etc.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any


class MatchMode(Enum):
    """Matching mode"""
    AUTO = "auto"
    RULE = "rule"


class AlignMode(Enum):
    """Alignment mode"""
    FAST = "fast"
    PRECISE = "precise"


class BgColor(Enum):
    """Background color type"""
    AUTO = "auto"
    BLACK = "black"
    WHITE = "white"
    CUSTOM = "custom"  # User-specified #RRGGBB


class JobStatus(Enum):
    """Job status"""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailReason(Enum):
    """Failure reason"""
    NONE = "none"
    NO_MATCH = "no_match"
    READ_FAIL = "read_fail"
    SIZE_INVALID = "size_invalid"
    ALIGN_FAIL = "align_fail"
    WRITE_FAIL = "write_fail"
    USER_SKIP = "user_skip"
    BG_REMOVE_FAIL = "bg_remove_fail"


@dataclass
class ImgInfo:
    """
    Image information (migrated from auto_match.py)
    Used to store metadata and features for each image during auto matching
    """
    path: Path
    filename: str
    group_key: str
    diff_index: Optional[int]
    has_diff_word: bool

    w: int
    h: int

    valid_ratio: float
    max_fill_cc_ratio: float
    fill_mode_ratio: float  # Maximum pixel ratio of "fill color candidates"

    is_diff: bool
    diff_score: float
    full_score: float


@dataclass
class PairJob:
    """
    Pair job: a processing unit with one base + one diff
    """
    base_path: Path
    diff_path: Path
    output_rel_path: Path  # Path relative to output_root

    # Metadata (optional, for logging/debugging)
    match_source: MatchMode = MatchMode.AUTO
    base_info: Optional[ImgInfo] = None
    diff_info: Optional[ImgInfo] = None


@dataclass
class AlignResult:
    """Alignment result"""
    dx: int = 0
    dy: int = 0
    distance: int = 0
    fit_percent: float = 0.0
    npixels: int = 0


@dataclass
class ReportItem:
    """
    Processing report item
    """
    status: JobStatus
    reason: FailReason = FailReason.NONE

    base_path: Optional[Path] = None
    diff_path: Optional[Path] = None
    output_path: Optional[Path] = None

    align_result: Optional[AlignResult] = None
    elapsed_ms: float = 0.0

    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == JobStatus.SUCCESS


@dataclass
class ProcessReport:
    """
    Processing summary report
    """
    items: list = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for it in self.items if it.status == JobStatus.SUCCESS)

    @property
    def failed_count(self) -> int:
        return sum(1 for it in self.items if it.status == JobStatus.FAILED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for it in self.items if it.status == JobStatus.SKIPPED)

    @property
    def total_count(self) -> int:
        return len(self.items)

    def add(self, item: ReportItem) -> None:
        self.items.append(item)

    def get_failures_by_reason(self) -> Dict[FailReason, list]:
        """Group by failure reason"""
        result: Dict[FailReason, list] = {}
        for it in self.items:
            if it.status == JobStatus.FAILED:
                result.setdefault(it.reason, []).append(it)
        return result

    def summary(self) -> str:
        """Generate summary text"""
        lines = [
            "=" * 50,
            "Processing Report",
            "=" * 50,
            f"Total: {self.total_count} items",
            f"  Success: {self.success_count}",
            f"  Failed: {self.failed_count}",
            f"  Skipped: {self.skipped_count}",
        ]

        failures = self.get_failures_by_reason()
        if failures:
            lines.append("")
            lines.append("Failure reason breakdown:")
            for reason, items in sorted(failures.items(), key=lambda x: -len(x[1])):
                lines.append(f"  {reason.value}: {len(items)} items")

        lines.append("=" * 50)
        return "\n".join(lines)


@dataclass
class AlignParams:
    """Alignment algorithm parameters"""
    init_step: int = 20
    step_divisor: int = 10
    ext_scale: int = 2

    @classmethod
    def fast(cls) -> "AlignParams":
        """Fast mode"""
        return cls(init_step=20, step_divisor=10, ext_scale=2)

    @classmethod
    def precise(cls) -> "AlignParams":
        """Precise mode"""
        return cls(init_step=1, step_divisor=3, ext_scale=1)
