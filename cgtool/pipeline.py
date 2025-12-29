"""
cgtool/pipeline.py
Task orchestration:
- Scan images
- Parallel processing
- dry-run / interactive mode
- Report aggregation
"""

import time
from pathlib import Path
from typing import List, Optional, Tuple, Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

from tqdm import tqdm

from .cgtypes import (
    PairJob,
    ReportItem,
    ProcessReport,
    JobStatus,
    FailReason,
    AlignParams,
    AlignResult,
    MatchMode,
    BgColor,
)
from .match import match_auto, match_rule, IMAGE_EXTS
from .imageops import (
    load_rgba,
    clear_color,
    detect_bg_color,
    align_image,
    compose_aligned,
    save_rgba,
)


def scan_images(input_root: Path, recursive: bool = False) -> List[Path]:
    """
    Scan image files in input directory
    """
    if recursive:
        paths = list(input_root.rglob("*"))
    else:
        paths = list(input_root.iterdir())
    
    return [p for p in paths if p.is_file() and p.suffix.lower() in IMAGE_EXTS]


def _process_job_impl(
    job: PairJob,
    output_root: Path,
    bg_color: Optional[Tuple[int, int, int]],
    tolerance: int,
    align_params: AlignParams,
    bg_mode: str,
) -> Tuple[ReportItem, Optional[AlignResult]]:
    """
    Process single job (worker function)
    """
    start_time = time.perf_counter()
    output_path = output_root / job.output_rel_path
    
    try:
        # Load images
        try:
            base_rgba = load_rgba(job.base_path)
        except Exception as e:
            return ReportItem(
                status=JobStatus.FAILED,
                reason=FailReason.READ_FAIL,
                base_path=job.base_path,
                diff_path=job.diff_path,
                extra={"error": f"Failed to read base image: {e}"},
            ), None
        
        try:
            diff_rgba = load_rgba(job.diff_path)
        except Exception as e:
            return ReportItem(
                status=JobStatus.FAILED,
                reason=FailReason.READ_FAIL,
                base_path=job.base_path,
                diff_path=job.diff_path,
                extra={"error": f"Failed to read diff image: {e}"},
            ), None
        
        # Check dimensions
        base_h, base_w = base_rgba.shape[:2]
        diff_h, diff_w = diff_rgba.shape[:2]
        
        if diff_w > base_w or diff_h > base_h:
            return ReportItem(
                status=JobStatus.FAILED,
                reason=FailReason.SIZE_INVALID,
                base_path=job.base_path,
                diff_path=job.diff_path,
                extra={"error": f"Diff({diff_w}x{diff_h}) larger than base({base_w}x{base_h})"},
            ), None
        
        # Background removal
        try:
            if bg_color is None:
                _, detected_color = detect_bg_color(diff_rgba)
                actual_bg = detected_color
            else:
                actual_bg = bg_color
            
            diff_rgba = clear_color(diff_rgba, actual_bg, tolerance, bg_mode)
        except Exception as e:
            return ReportItem(
                status=JobStatus.FAILED,
                reason=FailReason.BG_REMOVE_FAIL,
                base_path=job.base_path,
                diff_path=job.diff_path,
                extra={"error": f"Background removal failed: {e}"},
            ), None
        
        # Alignment
        try:
            align_result = align_image(base_rgba, diff_rgba, align_params)
        except Exception as e:
            return ReportItem(
                status=JobStatus.FAILED,
                reason=FailReason.ALIGN_FAIL,
                base_path=job.base_path,
                diff_path=job.diff_path,
                extra={"error": f"Alignment failed: {e}"},
            ), None
        
        # Compose and save
        try:
            output = compose_aligned(base_rgba, diff_rgba, align_result.dx, align_result.dy)
            save_rgba(output, output_path)
        except Exception as e:
            return ReportItem(
                status=JobStatus.FAILED,
                reason=FailReason.WRITE_FAIL,
                base_path=job.base_path,
                diff_path=job.diff_path,
                output_path=output_path,
                extra={"error": f"Save failed: {e}"},
            ), None
        
        elapsed = (time.perf_counter() - start_time) * 1000
        
        return ReportItem(
            status=JobStatus.SUCCESS,
            base_path=job.base_path,
            diff_path=job.diff_path,
            output_path=output_path,
            align_result=align_result,
            elapsed_ms=elapsed,
        ), align_result
    
    except Exception as e:
        return ReportItem(
            status=JobStatus.FAILED,
            reason=FailReason.ALIGN_FAIL,
            base_path=job.base_path,
            diff_path=job.diff_path,
            extra={"error": f"Unknown error: {e}"},
        ), None


# Top-level function for multiprocessing
def _worker_process_job(args):
    """Worker process function"""
    job, output_root, bg_color, tolerance, align_params, bg_mode = args
    return _process_job_impl(job, output_root, bg_color, tolerance, align_params, bg_mode)


class Pipeline:
    """
    Processing pipeline
    """
    
    def __init__(
        self,
        input_root: Path,
        output_root: Path,
        match_mode: MatchMode = MatchMode.AUTO,
        base_pattern: str = "*.png",
        diff_pattern: str = "*/diff*.png",
        recursive: bool = False,
        bg_color: Optional[Tuple[int, int, int]] = None,
        tolerance: int = 30,
        align_params: Optional[AlignParams] = None,
        bg_mode: str = "match",
        workers: int = 1,
        dry_run: bool = False,
        interactive: bool = False,
        verbose: bool = False,
    ):
        self.input_root = Path(input_root)
        self.output_root = Path(output_root)
        self.match_mode = match_mode
        self.base_pattern = base_pattern
        self.diff_pattern = diff_pattern
        self.recursive = recursive
        self.bg_color = bg_color
        self.tolerance = tolerance
        self.align_params = align_params or AlignParams.fast()
        self.bg_mode = bg_mode
        self.workers = workers
        self.dry_run = dry_run
        self.interactive = interactive
        self.verbose = verbose
        
        self.jobs: List[PairJob] = []
        self.report = ProcessReport()
    
    def match(self) -> List[PairJob]:
        """Execute matching"""
        if self.match_mode == MatchMode.AUTO:
            self.jobs = match_auto(self.input_root, self.recursive)
        else:
            self.jobs = match_rule(
                self.input_root,
                self.base_pattern,
                self.diff_pattern,
                self.recursive,
            )
        return self.jobs
    
    def print_dry_run(self) -> None:
        """Print dry-run info"""
        print("\n" + "=" * 60)
        print("DRY RUN - Preview files to be processed")
        print("=" * 60)
        print(f"Input directory: {self.input_root}")
        print(f"Output directory: {self.output_root}")
        print(f"Matching mode: {self.match_mode.value}")
        print(f"Pair count: {len(self.jobs)}")
        print("-" * 60)
        
        for i, job in enumerate(self.jobs, 1):
            print(f"\n[{i}] Pair:")
            print(f"    Base: {job.base_path.name}")
            print(f"    Diff: {job.diff_path.name}")
            print(f"    Output: {self.output_root / job.output_rel_path}")
        
        print("\n" + "=" * 60)
    
    def _confirm_job(self, job: PairJob, idx: int, total: int) -> bool:
        """Interactive confirmation for single job"""
        print(f"\n[{idx}/{total}] Confirm processing:")
        print(f"  Base: {job.base_path}")
        print(f"  Diff: {job.diff_path}")
        print(f"  Output: {self.output_root / job.output_rel_path}")
        
        while True:
            response = input("Continue? [y/n/a(ll)/q(uit)]: ").strip().lower()
            if response in ("y", "yes", ""):
                return True
            elif response in ("n", "no"):
                return False
            elif response in ("a", "all"):
                # Disable interactive mode
                self.interactive = False
                return True
            elif response in ("q", "quit"):
                raise KeyboardInterrupt("User cancelled")
        
    def run(self) -> ProcessReport:
        """
        Execute processing pipeline
        """
        # Matching
        if not self.jobs:
            self.match()
        
        if not self.jobs:
            print("No pairs found!")
            return self.report
        
        # Dry run
        if self.dry_run:
            self.print_dry_run()
            return self.report
        
        # Create output directory
        self.output_root.mkdir(parents=True, exist_ok=True)
        
        # Prepare tasks
        tasks_to_run = []
        for i, job in enumerate(self.jobs, 1):
            if self.interactive:
                try:
                    if not self._confirm_job(job, i, len(self.jobs)):
                        self.report.add(ReportItem(
                            status=JobStatus.SKIPPED,
                            reason=FailReason.USER_SKIP,
                            base_path=job.base_path,
                            diff_path=job.diff_path,
                        ))
                        continue
                except KeyboardInterrupt:
                    print("\nUser cancelled processing")
                    break
            
            tasks_to_run.append(job)
        
        if not tasks_to_run:
            return self.report
        
        # Execute processing
        if self.workers <= 1:
            # Single process
            for job in tqdm(tasks_to_run, desc="Processing"):
                report_item, _ = _process_job_impl(
                    job,
                    self.output_root,
                    self.bg_color,
                    self.tolerance,
                    self.align_params,
                    self.bg_mode,
                )
                self.report.add(report_item)
                
                if self.verbose and report_item.is_success:
                    ar = report_item.align_result
                    print(f"  {job.diff_path.name}: offset=({ar.dx}, {ar.dy}), match rate={ar.fit_percent:.1f}%")
        else:
            # Multi-process
            args_list = [
                (job, self.output_root, self.bg_color, self.tolerance, self.align_params, self.bg_mode)
                for job in tasks_to_run
            ]
            
            with ProcessPoolExecutor(max_workers=self.workers) as executor:
                futures = [executor.submit(_worker_process_job, args) for args in args_list]
                
                for future in tqdm(as_completed(futures), total=len(futures), desc="Processing"):
                    try:
                        report_item, align_result = future.result()
                        self.report.add(report_item)
                        
                        if self.verbose and report_item.is_success:
                            ar = report_item.align_result
                            print(f"  {report_item.diff_path.name}: offset=({ar.dx}, {ar.dy}), match rate={ar.fit_percent:.1f}%")
                    except Exception as e:
                        print(f"Process execution failed: {e}")
        
        return self.report


def run_pipeline(
    input_root: Path,
    output_root: Path,
    match_mode: MatchMode = MatchMode.AUTO,
    base_pattern: str = "*.png",
    diff_pattern: str = "*/diff*.png",
    recursive: bool = False,
    bg_color: Optional[Tuple[int, int, int]] = None,
    tolerance: int = 30,
    align_mode: str = "fast",
    bg_mode: str = "match",
    workers: int = 1,
    dry_run: bool = False,
    interactive: bool = False,
    verbose: bool = False,
) -> ProcessReport:
    """
    Convenience function: run processing pipeline
    """
    align_params = AlignParams.fast() if align_mode == "fast" else AlignParams.precise()
    
    pipeline = Pipeline(
        input_root=input_root,
        output_root=output_root,
        match_mode=match_mode,
        base_pattern=base_pattern,
        diff_pattern=diff_pattern,
        recursive=recursive,
        bg_color=bg_color,
        tolerance=tolerance,
        align_params=align_params,
        bg_mode=bg_mode,
        workers=workers,
        dry_run=dry_run,
        interactive=interactive,
        verbose=verbose,
    )
    
    return pipeline.run()
