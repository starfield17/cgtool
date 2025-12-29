# cgtool

CG Image Auto-Matching, Background Removal, and Alignment Tool.

## Features

- **Auto-Matching**: Automatically pair backgrounds and difference images based on filename rules and image features
- **Background Removal**: Auto-detect or specify background color with tolerance adjustment
- **Image Alignment**: Multi-resolution search algorithm for efficient and precise alignment
- **Batch Processing**: Multi-process parallel processing for large volumes of images
- **Graphical User Interface**: Easy-to-use GUI with preview, configuration, and progress tracking (requires PySide6)

## Installation

```bash
# Install from source
cd cgtool
pip install -e .

# For CLI only (default)
pip install -e .[cli]

# For GUI support
pip install -e .[gui]

# Or install all features
pip install -e .[all]

# Manual dependency installation
# CLI dependencies
pip install click numpy Pillow scipy numba tqdm

# GUI dependencies (optional)
pip install PySide6
```

## Quick Start

### GUI Mode (Recommended)

If PySide6 is installed, simply run:

```bash
# Launch GUI
cgtool-gui

# Or use the module entry point
python -m cgtool
```

The GUI provides:
- 📂 Browse input/output directories
- 🔍 Preview all matched pairs before processing
- ⚙️ Configure all parameters (matching mode, background, alignment, etc.)
- ✅ Select/deselect pairs with checkboxes
- 📊 Real-time progress tracking
- 📋 Detailed processing reports with error details
- 💾 Export reports to JSON

### CLI Mode

```bash
# Basic usage: auto-match and process
cgtool process ./input -o ./output

# Preview matching results (without actual processing)
cgtool process ./input -o ./output --dry-run

# Recursively scan subdirectories
cgtool process ./input -o ./output -r

# Use rule-based matching
cgtool process ./input -o ./output --match rule --diff-pattern "*/diff*.png"

# Specify background color and tolerance
cgtool process ./input -o ./output --bg-color black --tolerance 50

# Multi-process parallel processing
cgtool process ./input -o ./output -j 4

# Interactive mode, confirm each image
cgtool process ./input -o ./output -i
```

## Directory Structure

```
input/
  subject/20_nautical_miles.png    # Background image
  subject/20_nautical_miles/
    diff1.png                       # Difference image
    diff2.png

output/
  subject/20_nautical_miles/
    diff1.png                       # Composite image
    diff2.png
```

## GUI Usage Guide

### Overview

The graphical interface provides an intuitive way to configure and process CG images without using command-line arguments.

### Configuration Panel

**Directory Settings**
- **Input Directory**: Select the folder containing base and diff images
- **Output Directory**: Select where processed images will be saved

**Matching Options**
- **Match Mode**: Choose between `auto` (intelligent) or `rule` (pattern-based)
- **Base Pattern**: Pattern for base files (only when mode=rule)
- **Diff Pattern**: Pattern for diff files (only when mode=rule)
- **Recursive**: Enable to scan subdirectories

**Background Settings**
- **Auto Detect**: Automatically detect background color
- **Color**: Custom color selector (click to choose)
- **Tolerance**: Background removal threshold (0-255)
- **Mode**: `match` (RGB comparison) or `norm` (brightness-based)

**Processing Settings**
- **Align Mode**: `fast` (quick) or `precise` (accurate)
- **Workers**: Number of parallel processes (1-16)

### Workflow

1. **Select Directories**
   - Click "Browse..." to choose input and output directories

2. **Scan for Pairs**
   - Click "🔍 Scan" to detect all base/diff pairs
   - Review the list in the table preview

3. **Select Pairs to Process**
   - Use "Select All" / "Deselect All" for bulk selection
   - Or click individual checkboxes
   - Hover over rows to see full file paths

4. **Configure Parameters**
   - Adjust background, tolerance, alignment mode as needed
   - Click the color button to open color picker dialog

5. **Process**
   - Click "▶ Process Selected" to begin
   - Monitor progress in real-time
   - Click "Cancel" to stop processing

6. **Review Results**
   - Check the "Report" tab for detailed results
   - Success/failure status shown in table
   - Export report to JSON for analysis

### Table Columns

| Column | Description |
|--------|-------------|
| [ ] | Checkbox for selection |
| Base | Base image filename |
| Diff | Diff image filename |
| Output | Output path relative to output directory |
| Status | Processing result (✓ Success / ✗ Failed / ⊘ Skipped) |

**Color Indicators**
- ⚪ Normal (white): No conflicts
- 🟡 Yellow warning: Output file already exists (will be overwritten)
- 🔴 Red error: Multiple pairs output to same file (conflict)

### Report Tab

The Report tab shows:
- Summary statistics (total, success, failed, skipped)
- Detailed breakdown by failure reason
- Per-item results with alignment offsets and match rates
- Processing time for each pair

Use "Export JSON..." button to save the full report for further analysis or scripting.

## Commands

### `cgtool-gui`

Launch the graphical user interface (requires PySide6).

```
Usage: cgtool-gui
```

**Requirements**: PySide6 must be installed:
```bash
pip install cgtool[gui]
# or
pip install PySide6
```

### `cgtool process`

Process CG images, auto-match, remove background, align, and composite.

```
Usage: cgtool process [OPTIONS] INPUT_DIR

Arguments:
  INPUT_DIR               Input directory containing background and diff images (required)

Options:
  -o, --output PATH       Output directory (required)
  --match [auto|rule]     Matching mode
                           auto: Intelligent matching based on filename and image features
                           rule: Use specified glob patterns for matching
                           Default: auto
  --base-pattern TEXT     Background file matching pattern (only valid when match=rule)
                           Supports glob wildcards like "*.png", "{name}.png"
                           Default: "*.png"
  --diff-pattern TEXT     Diff file matching pattern (only valid when match=rule)
                           Supports glob wildcards like "*/diff*.png", "{name}/diff*.png"
                           Default: "*/diff*.png"
  -r, --recursive         Recursively scan all subdirectories
  --bg-color TEXT         Background color setting
                           auto: Auto-detect image background color
                           black: Black background
                           white: White background
                           #RRGGBB: Custom hex color
                           Default: auto
  --tolerance INT         Background removal tolerance value (0-255)
                           Larger values mean wider range of pixels considered as background
                           Used for handling impure backgrounds
                           Default: 30
  --bg-mode [match|norm]  Background removal mode
                           match: Compare RGB values with specified color
                           norm: Brightness-based detection (for solid color backgrounds)
                           Default: match
  --align-mode [fast|precise]
                           Alignment algorithm mode
                           fast: Fast mode using multi-resolution search, suitable for most cases
                           precise: Precise mode traversing all positions, slower but more accurate
                           Default: fast
  -j, --jobs INT          Number of parallel processes
                           Recommended to set to CPU cores for faster batch processing
                           Default: 1
  --dry-run               Preview mode: scan and display pairing info without actual execution
                           Suitable for checking correctness before processing
  -i, --interactive       Interactive mode: confirm each pairing one by one
                           Enter y/n to confirm or skip, a to process all remaining, q to cancel
  -v, --verbose           Verbose mode: show processing details for each image
                           Including alignment offset, match rate, and other statistics
  --report-json PATH      Save processing report to specified JSON file
                           Contains detailed info for each pairing: status, paths, alignment results, time, etc.
```

#### Processing Flow

1. **Scan**: Scan image files in input directory
2. **Match**: Pair background and diff images according to matching mode
3. **Remove Background**: Remove background color from diff image
4. **Align**: Align diff image to background image
5. **Composite**: Composite and save to output directory

### `cgtool scan`

Scan and display pairing results (without actual processing).

```
Usage: cgtool scan [OPTIONS] INPUT_DIR

Arguments:
  INPUT_DIR               Input directory (required)

Options:
  --match [auto|rule]     Matching mode
  --base-pattern TEXT     Background file matching pattern (only valid when match=rule)
  --diff-pattern TEXT     Diff file matching pattern (only valid when match=rule)
  -r, --recursive         Recursively scan all subdirectories
  --json                  Output pairing results in JSON format for script parsing
```

Examples:
```bash
# Scan and display pairing results
cgtool scan ./input

# Recursive scan using rule-based matching
cgtool scan ./input -r --match rule

# Output JSON format
cgtool scan ./input --json > pairs.json
```

### `cgtool info`

Display feature information for a single image.

```
Usage: cgtool info IMAGE_PATH

Arguments:
  IMAGE_PATH              Image file path (required)
```

Output information includes:
- Filename parsing results (group key, diff index, whether it contains diff keywords)
- Image dimensions (width x height)
- Image features (effective pixel ratio, largest fill connected component, fill color ratio)
- Detection results (whether it's a diff image, diff score, background score)

Example:
```bash
cgtool info ./image.png
```

## Matching Rules

### Auto-Matching Mode (auto)

1. Parse filename to extract `diffN` keyword and index
2. Calculate image features (effective pixel ratio, fill connected component ratio, etc.)
3. Classify background/diff based on features
4. Pair within same group by size and index

Supports:
- Full-width digits (`０`-`９`)
- Chinese paths and separators (`／`)

### Rule-Based Matching Mode (rule)

Use glob patterns to specify:
```bash
--base-pattern "*.png"
--diff-pattern "*/diff*.png"
```

## Alignment Algorithm

Ported from C# AutoCGAligner, using multi-resolution search strategy:

1. **Fast Mode** (fast)
   - Initial step size 20, quickly traverse full range
   - Gradually narrow range and step size
   - Suitable for most cases

2. **Precise Mode** (precise)
   - Step size 1, traverse all positions
   - Slower but more accurate
   - Used when fast mode fails

### Performance Optimization

- Use Numba JIT compilation for hot code paths
- Only compute edge pixels, avoid full-image traversal
- Early termination: exit when current distance exceeds minimum
- Support multi-process parallel processing

## Detailed Parameter Explanation

### Matching Mode Details

#### Auto-Matching Mode (auto)
- Automatically analyze filename, extract "diffN" keyword and index
- Calculate image features (effective pixel ratio, fill connected component ratio, etc.)
- Intelligently classify background and diff images based on features
- Automatically pair within same group by size and index

Features:
- No manual configuration needed
- Supports full-width digits (`０`-`９`)
- Supports Chinese paths and separators (`／`)
- Suitable for standard naming format files

#### Rule-Based Matching Mode (rule)
- User explicitly specifies background and diff image matching rules through glob patterns
- Provides more flexible control for non-standard naming formats

Common pattern examples:
```bash
# Background in root directory, diff in subdirectory
--base-pattern "*.png"
--diff-pattern "*/diff*.png"

# Diff image names contain "diff" prefix
--base-pattern "{name}.png"
--diff-pattern "{name}_diff*.png"

# Specific naming rules
--base-pattern "bg_*.png"
--diff-pattern "diff_*.png"
```

### Background Color Settings

#### auto (Auto-Detect)
- Tool automatically analyzes image to detect most common background color
- Suitable when background color is uncertain
- Detection algorithm based on pixel statistics and connected component analysis

#### black / white (Preset Colors)
- Black background: RGB(0, 0, 0)
- White background: RGB(255, 255, 255)
- Suitable when background color is known

#### #RRGGBB (Custom Color)
- Use hex color code to specify background color
- Example: `#ff0000` (red), `#00ff00` (green)
- Suitable for non-black/white solid color backgrounds

### Tolerance Parameter (--tolerance)

Tolerance determines background color detection range:

- **Small tolerance (10-20)**: Only remove pixels very close to target color
  - Suitable for pure backgrounds
  - May retain some background

- **Medium tolerance (30-50)**: Recommended range
  - Suitable for most cases
  - Can handle slight background color variations

- **Large tolerance (60-100)**: Remove wider range of colors
  - Suitable for impure backgrounds or backgrounds with noise
  - May incorrectly remove content

Suggestion: Start with default 30, adjust if needed. Use `--dry-run` to preview results.

### Alignment Mode

#### fast (Fast Mode)
- Initial step size 20, quickly traverse full range
- Gradually narrow range and step size
- Fast processing speed
- Suitable for most cases, accuracy is usually sufficient

#### precise (Precise Mode)
- Step size 1, traverse all possible positions
- Slower processing speed
- Higher accuracy
- Suitable for fast mode failures or when extremely high precision is needed

### Parallel Processing

Use `-j` parameter to specify number of parallel processes:

```bash
# Single process (default)
cgtool process ./input -o ./output -j 1

# 4 processes in parallel
cgtool process ./input -o ./output -j 4

# Auto-set based on CPU cores (example)
cgtool process ./input -o ./output -j $(nproc)
```

Suggestions:
- Few CPU cores (< 4): Use 2-4 processes
- Many CPU cores (>= 8): Use 50%-75% of CPU core count
- Many small files: Increase number of processes
- Few large files: Decrease number of processes

## Common Usage Scenarios

### Scenario 1: Standard Naming Format Batch Processing (GUI)

1. Launch GUI: `cgtool-gui`
2. Browse to input/output directories
3. Click "Scan" to detect pairs
4. Click "Select All" to process all
5. Adjust workers to 4 for parallel processing
6. Click "Process Selected"

### Scenario 2: CLI Batch Processing

```bash
cgtool process ./input -o ./output -j 4 -v
```
- Files follow "diffN" naming rule
- Multi-process acceleration
- Verbose output to view processing progress

### Scenario 3: Custom Naming Rules

**GUI:**
- Set Match Mode to "rule"
- Enter custom patterns in Base Pattern and Diff Pattern fields

**CLI:**
```bash
cgtool process ./input -o ./output   --match rule   --base-pattern "bg_*.png"   --diff-pattern "diff_*.png"
```

### Scenario 4: Complex Directory Structure

**GUI:**
- Enable "Recursive" checkbox
- Select background color (or use auto-detect)
- Adjust tolerance slider to 40

**CLI:**
```bash
cgtool process ./input -o ./output -r --bg-color black --tolerance 40
```

### Scenario 5: Preview Check Before Processing

**GUI:**
- Scan and review all pairs in the table
- Check for conflicts (highlighted in red)
- Hover over rows to see full paths
- Select/deselect as needed before processing

**CLI:**
```bash
# Preview first
cgtool process ./input -o ./output --dry-run

# Process after confirmation
cgtool process ./input -o ./output -j 4
```

### Scenario 6: Generate Processing Report

**GUI:**
- After processing, check the "Report" tab
- Click "Export JSON..." to save detailed report

**CLI:**
```bash
cgtool process ./input -o ./output   --report-json report.json   -v
```

### Scenario 7: Interactive Processing for Important Files

**GUI:**
- Use checkboxes to select only important pairs
- Review details by clicking on each row

**CLI:**
```bash
cgtool process ./input -o ./output -i
```

## Troubleshooting

### GUI Not Launching

**Problem**: Running `cgtool-gui` or `python -m cgtool` shows error about PySide6

**Solution**:
```bash
pip install PySide6
# or
pip install cgtool[gui]
```

**Alternative**: Use CLI mode directly with `cgtool <command>`.

### No Pairs Found

**GUI**:
1. Check input directory path is correct
2. Try enabling "Recursive" checkbox
3. Switch Match Mode to "rule" and adjust patterns
4. Click "Scan" again

**CLI**:
1. Check if filenames follow the matching mode
2. Use `cgtool scan ./input` to view scan results
3. Try rule-based matching mode
4. Check if `-r` recursive scan is needed

### Poor Background Removal Results

**GUI**:
1. Disable "Auto Detect" and manually pick background color
2. Increase "Tolerance" value
3. Try switching "Mode" between match/norm

**CLI**:
1. Adjust `--tolerance` parameter
2. Try specifying explicit background color `--bg-color`
3. Switch `--bg-mode` mode
4. Use `cgtool info ./image.png` to view image features

### Inaccurate Alignment

**GUI**:
1. Change "Align Mode" to "precise"
2. Check table for size warnings

**CLI**:
1. Switch to `--align-mode precise` for precise mode
2. Check if background and diff image dimensions are reasonable
3. Use `-v` verbose mode to view alignment parameters

### Slow Processing Speed

**GUI**:
1. Reduce "Workers" number (if memory is insufficient)
2. Use "fast" alignment mode

**CLI**:
1. Reduce number of parallel processes (if memory is insufficient)
2. Use fast alignment mode `--align-mode fast`
3. Check for large resolution images

## Usage as a Library

```python
from cgtool import (
    match_auto,
    load_rgba,
    clear_color,
    align_image,
    compose_aligned,
    save_rgba,
    AlignParams,
)
from pathlib import Path

# Pairing
jobs = match_auto(Path("./input"), recursive=True)

# Process single pairing
for job in jobs:
    base = load_rgba(job.base_path)
    diff = load_rgba(job.diff_path)
    
    # Remove background
    diff = clear_color(diff, (0, 0, 0), tolerance=30)
    
    # Align
    result = align_image(base, diff, AlignParams.fast())
    print(f"Offset: ({result.dx}, {result.dy}), Match rate: {result.fit_percent:.1f}%")
    
    # Composite
    output = compose_aligned(base, diff, result.dx, result.dy)
    save_rgba(output, Path("./output") / job.output_rel_path)
```

## Architecture

```
cgtool/
├── cgtypes.py          # Data structures (ImgInfo, PairJob, ReportItem, etc.)
├── match.py            # Auto/rule matching logic
├── imageops.py         # Background removal, alignment, composition
├── pipeline.py         # Processing orchestration, parallel execution
├── cli.py              # Command-line interface
├── gui.py              # Graphical user interface (PySide6)
├── __init__.py         # Package exports
└── __main__.py         # Entry point (GUI → CLI fallback)
```

## License

MIT License
