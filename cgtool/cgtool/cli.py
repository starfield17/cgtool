"""
cgtool/cli.py
Command-line interface (using click)
"""

import sys
import json
import re
from pathlib import Path
from typing import Optional

import click

from .types import MatchMode, AlignParams
from .pipeline import run_pipeline


def parse_color(color_str: str) -> tuple:
    """
    Parse color string
    Supported formats: black, white, #RRGGBB, rgb(r,g,b)
    """
    color_str = color_str.strip().lower()
    
    if color_str == "black":
        return (0, 0, 0)
    elif color_str == "white":
        return (255, 255, 255)
    elif color_str.startswith("#"):
        # #RRGGBB
        hex_str = color_str[1:]
        if len(hex_str) == 6:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return (r, g, b)
        elif len(hex_str) == 3:
            r = int(hex_str[0], 16) * 17
            g = int(hex_str[1], 16) * 17
            b = int(hex_str[2], 16) * 17
            return (r, g, b)
    elif color_str.startswith("rgb("):
        # rgb(r, g, b)
        match = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", color_str)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    
    raise ValueError(f"Unable to parse color: {color_str}")

@click.group()
@click.version_option(version="1.0.0", prog_name="cgtool")
def cli():
    """
    CG Image Processing Tool
    
    Automatically pair base and diff images, remove background color, align and compose images.
    
    \b
    Core Features:
    * Auto Matching:      Intelligently pair base and diff images based on filename
    * Background Removal: Auto-detect or specify background color with tolerance
    * Image Alignment:    Multi-resolution search algorithm for precision
    * Batch Processing:   Support for multi-process parallel processing
    
    \b
    Common Examples:
    
      # Basic usage - auto mode
      cgtool process ./input -o ./output
      
      # Preview mode (dry-run)
      cgtool process ./input -o ./output --dry-run
      
      # Recursively scan subdirectories
      cgtool process ./input -o ./output -r
      
      # Use rule matching mode
      cgtool process ./input -o ./output --match rule --diff-pattern "*/diff*.png"
      
      # Specify black background with higher tolerance
      cgtool process ./input -o ./output --bg-color black --tolerance 50
      
      # Multi-process parallel processing (4 processes)
      cgtool process ./input -o ./output -j 4
      
      # Interactive mode
      cgtool process ./input -o ./output -i
      
      # Verbose output + JSON report
      cgtool process ./input -o ./output -v --report-json report.json
    """
    pass



@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-o", "--output", "output_dir", type=click.Path(path_type=Path), required=True,
              help="Output directory (required)")
@click.option("--match", "match_mode", type=click.Choice(["auto", "rule"]), default="auto",
              help="[auto|rule] Matching mode. auto: intelligent matching based on filename and image features; rule: use specified glob patterns (default: auto)")
@click.option("--base-pattern", default="*.png",
              help="Base file matching pattern (only valid when match=rule). Supports glob wildcards like \"*.png\", \"{name}.png\" (default: \"*.png\")")
@click.option("--diff-pattern", default="*/diff*.png",
              help="Diff file matching pattern (only valid when match=rule). Supports glob wildcards like \"*/diff*.png\", \"{name}/diff*.png\" (default: \"*/diff*.png\")")
@click.option("-r", "--recursive", is_flag=True,
              help="Recursively scan all subdirectories")
@click.option("--bg-color", default=None,
              help="Background color setting. auto: auto-detect image background color; black: black background; white: white background; #RRGGBB: custom hex color (default: auto)")
@click.option("--tolerance", type=click.IntRange(0, 255), default=30,
              help="Background removal tolerance value (0-255). Larger values expand the range of pixels considered as background. Used for handling impure backgrounds (default: 30)")
@click.option("--bg-mode", type=click.Choice(["match", "norm"]), default="match",
              help="[match|norm] Background removal mode. match: compare RGB values with specified color; norm: determine by brightness (suitable for solid backgrounds) (default: match)")
@click.option("--align-mode", type=click.Choice(["fast", "precise"]), default="fast",
              help="[fast|precise] Alignment algorithm mode. fast: quick mode using multi-resolution search, suitable for most scenarios; precise: exact mode traversing all positions, slower but more accurate (default: fast)")
@click.option("-j", "--jobs", type=int, default=1,
              help="Number of parallel processes. Recommended to set to CPU core count for faster batch processing (default: 1)")
@click.option("--dry-run", is_flag=True,
              help="Preview mode: scan and display pair information to be processed, but do not actually perform any processing. Suitable for checking if pairs are correct before formal processing")
@click.option("-i", "--interactive", is_flag=True,
              help="Interactive mode: confirm processing for each pair one by one. Input y/n to confirm or skip, a to process all remaining, q to cancel processing")
@click.option("-v", "--verbose", is_flag=True,
              help="Verbose output mode: display processing details for each image, including alignment offset, match rate, and other statistics")
@click.option("--report-json", type=click.Path(path_type=Path), default=None,
              help="Save processing report to specified JSON file, containing detailed information for each pair: processing status, paths, alignment results, time taken, etc.")
def process(
    input_dir: Path,
    output_dir: Path,
    match_mode: str,
    base_pattern: str,
    diff_pattern: str,
    recursive: bool,
    bg_color: Optional[str],
    tolerance: int,
    bg_mode: str,
    align_mode: str,
    jobs: int,
    dry_run: bool,
    interactive: bool,
    verbose: bool,
    report_json: Optional[Path],
):
    """
    Process CG images
    
    INPUT_DIR: Input directory containing base and diff images.
    
    \b
    Processing Flow:
      1. Scan image files in input directory
      2. Pair base and diff images according to matching mode
      3. Remove background color from diff image
      4. Align diff image to base image
      5. Compose and save to output directory
    
    \b
    Output Structure:
      Maintains diff image's relative path structure to input directory
    """
    # Parse background color
    parsed_bg_color = None
    if bg_color and bg_color.lower() != "auto":
        try:
            parsed_bg_color = parse_color(bg_color)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
    
    # Convert matching mode
    mode = MatchMode.AUTO if match_mode == "auto" else MatchMode.RULE
    
    click.echo(f"Input directory: {input_dir}")
    click.echo(f"Output directory: {output_dir}")
    click.echo(f"Matching mode: {match_mode}")
    click.echo(f"Alignment mode: {align_mode}")
    if verbose:
        click.echo(f"Background color: {bg_color or 'auto'}")
        click.echo(f"Tolerance: {tolerance}")
        click.echo(f"Parallel processes: {jobs}")
    click.echo()
    
    try:
        report = run_pipeline(
            input_root=input_dir,
            output_root=output_dir,
            match_mode=mode,
            base_pattern=base_pattern,
            diff_pattern=diff_pattern,
            recursive=recursive,
            bg_color=parsed_bg_color,
            tolerance=tolerance,
            align_mode=align_mode,
            bg_mode=bg_mode,
            workers=jobs,
            dry_run=dry_run,
            interactive=interactive,
            verbose=verbose,
        )
        
        # Output report
        click.echo()
        click.echo(report.summary())
        
        # Save JSON report
        if report_json:
            report_data = {
                "total": report.total_count,
                "success": report.success_count,
                "failed": report.failed_count,
                "skipped": report.skipped_count,
                "items": [
                    {
                        "status": item.status.value,
                        "reason": item.reason.value if item.reason else None,
                        "base_path": str(item.base_path) if item.base_path else None,
                        "diff_path": str(item.diff_path) if item.diff_path else None,
                        "output_path": str(item.output_path) if item.output_path else None,
                        "dx": item.align_result.dx if item.align_result else None,
                        "dy": item.align_result.dy if item.align_result else None,
                        "fit_percent": item.align_result.fit_percent if item.align_result else None,
                        "elapsed_ms": item.elapsed_ms,
                        "extra": item.extra,
                    }
                    for item in report.items
                ],
            }
            report_json.parent.mkdir(parents=True, exist_ok=True)
            with open(report_json, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
            click.echo(f"\nReport saved: {report_json}")
        
        # Return status code
        if report.failed_count > 0:
            sys.exit(1)
    
    except KeyboardInterrupt:
        click.echo("\nUser cancelled")
        sys.exit(130)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--match", "match_mode", type=click.Choice(["auto", "rule"]), default="auto",
              help="[auto|rule] Matching mode. auto: intelligent matching; rule: use specified patterns (default: auto)")
@click.option("--base-pattern", default="*.png",
              help="Base file matching pattern (only valid when match=rule) (default: \"*.png\")")
@click.option("--diff-pattern", default="*/diff*.png",
              help="Diff file matching pattern (only valid when match=rule) (default: \"*/diff*.png\")")
@click.option("-r", "--recursive", is_flag=True,
              help="Recursively scan all subdirectories")
@click.option("--json", "as_json", is_flag=True, help="Output pairing results in JSON format for script parsing")
def scan(
    input_dir: Path,
    match_mode: str,
    base_pattern: str,
    diff_pattern: str,
    recursive: bool,
    as_json: bool,
):
    """
    Scan and display pairing results (without actual processing)
    
    INPUT_DIR: Input directory
    
    This command only scans and pairs, without performing image processing. Suitable for checking if pairs are correct before formal processing.
    Output includes: base file, diff file, output path, etc.
    
    Example:
      cgtool scan ./input
      cgtool scan ./input --json > pairs.json
      cgtool scan ./input -r --match rule
    """
    from .match import match_auto, match_rule
    
    mode = MatchMode.AUTO if match_mode == "auto" else MatchMode.RULE
    
    if mode == MatchMode.AUTO:
        jobs = match_auto(input_dir, recursive)
    else:
        jobs = match_rule(input_dir, base_pattern, diff_pattern, recursive)
    
    if as_json:
        data = [
            {
                "base": str(j.base_path),
                "diff": str(j.diff_path),
                "output_rel": str(j.output_rel_path),
            }
            for j in jobs
        ]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        click.echo(f"Found {len(jobs)} pairs:\n")
        for i, job in enumerate(jobs, 1):
            click.echo(f"[{i}]")
            click.echo(f"  Base: {job.base_path.name}")
            click.echo(f"  Diff: {job.diff_path.name}")
            if job.diff_info:
                click.echo(f"  Diff score: {job.diff_info.diff_score:.2f}")
            click.echo()


@cli.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def info(image_path: Path):
    """
    Display image feature information
    
    IMAGE_PATH: Image file path
    
    Output information includes:
      - Filename parsing results (group key, diff index, whether it contains diff keyword)
      - Image dimensions (width x height)
      - Image features (valid pixel ratio, max fill connected component, fill color ratio)
      - Decision results (whether it's a diff image, diff score, background score)
    
    Example:
      cgtool info ./image.png
    """
    from .match import compute_features, decide_diff, parse_name, split_name_no_ext
    
    name_no_ext = split_name_no_ext(image_path.name)
    group_key, diff_index, has_diff_word = parse_name(name_no_ext)
    
    w, h, valid_ratio, max_fill_cc_ratio, fill_mode_ratio = compute_features(image_path)
    is_diff, diff_score, full_score = decide_diff(valid_ratio, max_fill_cc_ratio)
    
    click.echo(f"File: {image_path.name}")
    click.echo(f"Size: {w} x {h}")
    click.echo()
    click.echo("Filename parsing:")
    click.echo(f"  Group key: {group_key}")
    click.echo(f"  Diff index: {diff_index}")
    click.echo(f"  Contains 'diff' word: {has_diff_word}")
    click.echo()
    click.echo("Image features:")
    click.echo(f"  Valid pixel ratio: {valid_ratio:.2%}")
    click.echo(f"  Max fill connected component: {max_fill_cc_ratio:.2%}")
    click.echo(f"  Fill color ratio: {fill_mode_ratio:.2%}")
    click.echo()
    click.echo("Decision results:")
    click.echo(f"  Is diff: {'Yes' if is_diff else 'No'}")
    click.echo(f"  Diff score: {diff_score:.2f}")
    click.echo(f"  Background score: {full_score:.2f}")


def main():
    """Entry point"""
    cli()


if __name__ == "__main__":
    main()
