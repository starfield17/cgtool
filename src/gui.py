"""
cgtool/gui.py
PySide6 GUI for cgtool

Features:
- Scan and preview pairs in a table with checkboxes
- Configure all processing parameters
- Process selected pairs with progress feedback
- Display detailed reports with error information
"""

import sys
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QTextEdit, QFileDialog, QMessageBox,
    QSplitter, QTabWidget, QStatusBar, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QIcon


# Import cgtool modules
from .cgtypes import (
    PairJob, ProcessReport, ReportItem, JobStatus, FailReason,
    MatchMode, AlignParams,
)
from .match import match_auto, match_rule
from .pipeline import Pipeline


@dataclass
class ScanResult:
    """Scan result data"""
    jobs: List[PairJob]
    input_root: Path
    output_root: Path


class ScanWorker(QThread):
    """Worker thread for scanning"""
    finished = Signal(object)  # ScanResult or Exception
    
    def __init__(
        self,
        input_root: Path,
        output_root: Path,
        match_mode: MatchMode,
        base_pattern: str,
        diff_pattern: str,
        recursive: bool,
    ):
        super().__init__()
        self.input_root = input_root
        self.output_root = output_root
        self.match_mode = match_mode
        self.base_pattern = base_pattern
        self.diff_pattern = diff_pattern
        self.recursive = recursive
    
    def run(self):
        try:
            if self.match_mode == MatchMode.AUTO:
                jobs = match_auto(self.input_root, self.recursive)
            else:
                jobs = match_rule(
                    self.input_root,
                    self.base_pattern,
                    self.diff_pattern,
                    self.recursive,
                )
            result = ScanResult(
                jobs=jobs,
                input_root=self.input_root,
                output_root=self.output_root,
            )
            self.finished.emit(result)
        except Exception as e:
            self.finished.emit(e)


class ProcessWorker(QThread):
    """Worker thread for processing"""
    progress = Signal(int, int, str)  # current, total, message
    finished = Signal(object)  # ProcessReport or Exception
    
    def __init__(
        self,
        input_root: Path,
        output_root: Path,
        jobs: List[PairJob],
        bg_color: Optional[Tuple[int, int, int]],
        tolerance: int,
        bg_mode: str,
        align_mode: str,
        workers: int,
    ):
        super().__init__()
        self.input_root = input_root
        self.output_root = output_root
        self.jobs = jobs
        self.bg_color = bg_color
        self.tolerance = tolerance
        self.bg_mode = bg_mode
        self.align_mode = align_mode
        self.workers = workers
        self._cancelled = False
    
    def cancel(self):
        """Request cancellation"""
        self._cancelled = True
    
    def _check_cancel(self) -> bool:
        return self._cancelled
    
    def _progress_callback(self, current: int, total: int, message: str):
        self.progress.emit(current, total, message)
    
    def run(self):
        try:
            align_params = AlignParams.fast() if self.align_mode == "fast" else AlignParams.precise()
            
            pipeline = Pipeline(
                input_root=self.input_root,
                output_root=self.output_root,
                bg_color=self.bg_color,
                tolerance=self.tolerance,
                align_params=align_params,
                bg_mode=self.bg_mode,
                workers=self.workers,
                interactive=False,  # Never use interactive in GUI
                verbose=False,
            )
            
            report = pipeline.run(
                jobs_override=self.jobs,
                progress_callback=self._progress_callback,
                cancel_check=self._check_cancel,
            )
            self.finished.emit(report)
        except Exception as e:
            self.finished.emit(e)


class ColorButton(QPushButton):
    """Button for color selection"""
    colorChanged = Signal(tuple)
    
    def __init__(self, color: Tuple[int, int, int] = (0, 0, 0)):
        super().__init__()
        self._color = color
        self._update_style()
        self.clicked.connect(self._on_click)
        self.setFixedSize(60, 25)
    
    @property
    def color(self) -> Tuple[int, int, int]:
        return self._color
    
    @color.setter
    def color(self, value: Tuple[int, int, int]):
        self._color = value
        self._update_style()
        self.colorChanged.emit(value)
    
    def _update_style(self):
        r, g, b = self._color
        # Determine text color based on background brightness
        brightness = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "white" if brightness < 128 else "black"
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); color: {text_color}; border: 1px solid #888;"
        )
        self.setText(f"#{r:02X}{g:02X}{b:02X}")
    
    def _on_click(self):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor as QC
        
        initial = QC(*self._color)
        color = QColorDialog.getColor(initial, self, "Select Background Color")
        if color.isValid():
            self.color = (color.red(), color.green(), color.blue())


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CGTool - CG Image Processing Tool")
        self.setMinimumSize(1000, 700)
        
        # State
        self.scan_result: Optional[ScanResult] = None
        self.scan_worker: Optional[ScanWorker] = None
        self.process_worker: Optional[ProcessWorker] = None
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Setup the user interface"""
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Top: Configuration panel
        config_widget = self._create_config_panel()
        main_layout.addWidget(config_widget)
        
        # Middle: Splitter with table and details
        splitter = QSplitter(Qt.Horizontal)
        
        # Left: Pairs table
        table_group = self._create_table_panel()
        splitter.addWidget(table_group)
        
        # Right: Details and log
        right_widget = self._create_right_panel()
        splitter.addWidget(right_widget)
        
        splitter.setSizes([600, 400])
        main_layout.addWidget(splitter, 1)
        
        # Bottom: Progress and actions
        bottom_widget = self._create_bottom_panel()
        main_layout.addWidget(bottom_widget)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
    
    def _create_config_panel(self) -> QWidget:
        """Create configuration panel"""
        group = QGroupBox("Configuration")
        layout = QGridLayout(group)
        layout.setSpacing(8)
        
        row = 0
        
        # Input directory
        layout.addWidget(QLabel("Input Directory:"), row, 0)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select input directory containing images...")
        layout.addWidget(self.input_edit, row, 1)
        self.input_btn = QPushButton("Browse...")
        self.input_btn.setFixedWidth(80)
        layout.addWidget(self.input_btn, row, 2)
        
        row += 1
        
        # Output directory
        layout.addWidget(QLabel("Output Directory:"), row, 0)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Select output directory...")
        layout.addWidget(self.output_edit, row, 1)
        self.output_btn = QPushButton("Browse...")
        self.output_btn.setFixedWidth(80)
        layout.addWidget(self.output_btn, row, 2)
        
        row += 1
        
        # Match mode and patterns
        layout.addWidget(QLabel("Match Mode:"), row, 0)
        match_layout = QHBoxLayout()
        self.match_combo = QComboBox()
        self.match_combo.addItems(["auto", "rule"])
        self.match_combo.setFixedWidth(80)
        match_layout.addWidget(self.match_combo)
        
        match_layout.addWidget(QLabel("Base Pattern:"))
        self.base_pattern_edit = QLineEdit("*.png")
        self.base_pattern_edit.setFixedWidth(120)
        self.base_pattern_edit.setEnabled(False)
        match_layout.addWidget(self.base_pattern_edit)
        
        match_layout.addWidget(QLabel("Diff Pattern:"))
        self.diff_pattern_edit = QLineEdit("*/diff*.png")
        self.diff_pattern_edit.setFixedWidth(120)
        self.diff_pattern_edit.setEnabled(False)
        match_layout.addWidget(self.diff_pattern_edit)
        
        self.recursive_check = QCheckBox("Recursive")
        match_layout.addWidget(self.recursive_check)
        match_layout.addStretch()
        
        layout.addLayout(match_layout, row, 1, 1, 2)
        
        row += 1
        
        # Background settings
        layout.addWidget(QLabel("Background:"), row, 0)
        bg_layout = QHBoxLayout()
        
        self.bg_auto_check = QCheckBox("Auto Detect")
        self.bg_auto_check.setChecked(True)
        bg_layout.addWidget(self.bg_auto_check)
        
        bg_layout.addWidget(QLabel("Color:"))
        self.bg_color_btn = ColorButton((0, 0, 0))
        self.bg_color_btn.setEnabled(False)
        bg_layout.addWidget(self.bg_color_btn)
        
        bg_layout.addWidget(QLabel("Tolerance:"))
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 255)
        self.tolerance_spin.setValue(30)
        self.tolerance_spin.setFixedWidth(60)
        bg_layout.addWidget(self.tolerance_spin)
        
        bg_layout.addWidget(QLabel("Mode:"))
        self.bg_mode_combo = QComboBox()
        self.bg_mode_combo.addItems(["match", "norm"])
        self.bg_mode_combo.setFixedWidth(80)
        bg_layout.addWidget(self.bg_mode_combo)
        bg_layout.addStretch()
        
        layout.addLayout(bg_layout, row, 1, 1, 2)
        
        row += 1
        
        # Alignment and workers
        layout.addWidget(QLabel("Processing:"), row, 0)
        proc_layout = QHBoxLayout()
        
        proc_layout.addWidget(QLabel("Align Mode:"))
        self.align_combo = QComboBox()
        self.align_combo.addItems(["fast", "precise"])
        self.align_combo.setFixedWidth(80)
        proc_layout.addWidget(self.align_combo)
        
        proc_layout.addWidget(QLabel("Workers:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(1)
        self.workers_spin.setFixedWidth(60)
        self.workers_spin.setToolTip("Number of parallel processes (1 = single process, recommended for stability)")
        proc_layout.addWidget(self.workers_spin)
        proc_layout.addStretch()
        
        layout.addLayout(proc_layout, row, 1, 1, 2)
        
        return group
    
    def _create_table_panel(self) -> QWidget:
        """Create pairs table panel"""
        group = QGroupBox("Pairs Preview")
        layout = QVBoxLayout(group)
        
        # Table toolbar
        toolbar = QHBoxLayout()
        self.scan_btn = QPushButton("🔍 Scan")
        self.scan_btn.setFixedWidth(100)
        toolbar.addWidget(self.scan_btn)
        
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(80)
        self.select_all_btn.setEnabled(False)
        toolbar.addWidget(self.select_all_btn)
        
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.setFixedWidth(80)
        self.deselect_all_btn.setEnabled(False)
        toolbar.addWidget(self.deselect_all_btn)
        
        toolbar.addStretch()
        
        self.pairs_count_label = QLabel("0 pairs")
        toolbar.addWidget(self.pairs_count_label)
        
        layout.addLayout(toolbar)
        
        # Table
        self.pairs_table = QTableWidget()
        self.pairs_table.setColumnCount(5)
        self.pairs_table.setHorizontalHeaderLabels(["", "Base", "Diff", "Output", "Status"])
        self.pairs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.pairs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.pairs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.pairs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.pairs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.pairs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pairs_table.setAlternatingRowColors(True)
        layout.addWidget(self.pairs_table)
        
        return group
    
    def _create_right_panel(self) -> QWidget:
        """Create right panel with details and log"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Tab widget
        tabs = QTabWidget()
        
        # Details tab
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlaceholderText("Select a pair to view details...")
        details_layout.addWidget(self.details_text)
        
        tabs.addTab(details_widget, "Details")
        
        # Report tab
        report_widget = QWidget()
        report_layout = QVBoxLayout(report_widget)
        
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setPlaceholderText("Processing report will appear here...")
        self.report_text.setFont(QFont("Consolas", 9))
        report_layout.addWidget(self.report_text)
        
        # Export button
        export_layout = QHBoxLayout()
        export_layout.addStretch()
        self.export_btn = QPushButton("Export JSON...")
        self.export_btn.setEnabled(False)
        export_layout.addWidget(self.export_btn)
        report_layout.addLayout(export_layout)
        
        tabs.addTab(report_widget, "Report")
        
        layout.addWidget(tabs)
        return widget
    
    def _create_bottom_panel(self) -> QWidget:
        """Create bottom panel with progress and actions"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Progress
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel("")
        self.progress_label.setFixedWidth(300)
        progress_layout.addWidget(self.progress_label)
        
        layout.addLayout(progress_layout)
        
        # Actions
        actions_layout = QHBoxLayout()
        actions_layout.addStretch()
        
        self.process_btn = QPushButton("▶ Process Selected")
        self.process_btn.setFixedWidth(140)
        self.process_btn.setEnabled(False)
        actions_layout.addWidget(self.process_btn)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.setEnabled(False)
        actions_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(actions_layout)
        
        return widget
    
    def _connect_signals(self):
        """Connect widget signals"""
        # Directory browsing
        self.input_btn.clicked.connect(self._browse_input)
        self.output_btn.clicked.connect(self._browse_output)
        
        # Match mode
        self.match_combo.currentTextChanged.connect(self._on_match_mode_changed)
        
        # Background auto
        self.bg_auto_check.toggled.connect(lambda checked: self.bg_color_btn.setEnabled(not checked))
        
        # Table selection
        self.pairs_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.select_all_btn.clicked.connect(self._select_all)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        
        # Actions
        self.scan_btn.clicked.connect(self._on_scan)
        self.process_btn.clicked.connect(self._on_process)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.export_btn.clicked.connect(self._on_export)
    
    def _browse_input(self):
        """Browse for input directory"""
        path = QFileDialog.getExistingDirectory(self, "Select Input Directory")
        if path:
            self.input_edit.setText(path)
    
    def _browse_output(self):
        """Browse for output directory"""
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if path:
            self.output_edit.setText(path)
    
    def _on_match_mode_changed(self, mode: str):
        """Handle match mode change"""
        is_rule = mode == "rule"
        self.base_pattern_edit.setEnabled(is_rule)
        self.diff_pattern_edit.setEnabled(is_rule)
    
    def _on_table_selection_changed(self):
        """Handle table selection change"""
        rows = self.pairs_table.selectionModel().selectedRows()
        if not rows or not self.scan_result:
            self.details_text.clear()
            return
        
        row = rows[0].row()
        if row < len(self.scan_result.jobs):
            job = self.scan_result.jobs[row]
            self._show_job_details(job)
    
    def _show_job_details(self, job: PairJob):
        """Show details for a job"""
        lines = [
            f"<b>Base Image:</b><br>{job.base_path}",
            "",
            f"<b>Diff Image:</b><br>{job.diff_path}",
            "",
            f"<b>Output Path:</b><br>{self.scan_result.output_root / job.output_rel_path}",
        ]
        
        if job.base_info:
            lines.extend([
                "",
                "<b>Base Info:</b>",
                f"  Size: {job.base_info.w} × {job.base_info.h}",
                f"  Valid Ratio: {job.base_info.valid_ratio:.2%}",
                f"  Is Diff: {'Yes' if job.base_info.is_diff else 'No'}",
            ])
        
        if job.diff_info:
            lines.extend([
                "",
                "<b>Diff Info:</b>",
                f"  Size: {job.diff_info.w} × {job.diff_info.h}",
                f"  Valid Ratio: {job.diff_info.valid_ratio:.2%}",
                f"  Diff Score: {job.diff_info.diff_score:.2f}",
            ])
        
        self.details_text.setHtml("<br>".join(lines))
    
    def _select_all(self):
        """Select all pairs"""
        for row in range(self.pairs_table.rowCount()):
            item = self.pairs_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked)
        self._update_process_btn()
    
    def _deselect_all(self):
        """Deselect all pairs"""
        for row in range(self.pairs_table.rowCount()):
            item = self.pairs_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Unchecked)
        self._update_process_btn()
    
    def _get_selected_jobs(self) -> List[PairJob]:
        """Get list of selected jobs"""
        if not self.scan_result:
            return []
        
        selected = []
        for row in range(self.pairs_table.rowCount()):
            item = self.pairs_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                if row < len(self.scan_result.jobs):
                    selected.append(self.scan_result.jobs[row])
        return selected
    
    def _update_process_btn(self):
        """Update process button state"""
        selected = self._get_selected_jobs()
        self.process_btn.setEnabled(len(selected) > 0 and self.process_worker is None)
        self.process_btn.setText(f"▶ Process Selected ({len(selected)})")
    
    def _on_scan(self):
        """Handle scan button click"""
        # Validate inputs
        input_dir = self.input_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        
        if not input_dir:
            QMessageBox.warning(self, "Error", "Please select an input directory.")
            return
        if not output_dir:
            QMessageBox.warning(self, "Error", "Please select an output directory.")
            return
        
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        if not input_path.exists():
            QMessageBox.warning(self, "Error", f"Input directory does not exist:\n{input_path}")
            return
        
        # Get settings
        match_mode = MatchMode.AUTO if self.match_combo.currentText() == "auto" else MatchMode.RULE
        
        # Start scan
        self.scan_btn.setEnabled(False)
        self.statusBar.showMessage("Scanning...")
        
        self.scan_worker = ScanWorker(
            input_root=input_path,
            output_root=output_path,
            match_mode=match_mode,
            base_pattern=self.base_pattern_edit.text(),
            diff_pattern=self.diff_pattern_edit.text(),
            recursive=self.recursive_check.isChecked(),
        )
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.start()
    
    def _on_scan_finished(self, result):
        """Handle scan completion"""
        self.scan_btn.setEnabled(True)
        self.scan_worker = None
        
        if isinstance(result, Exception):
            QMessageBox.critical(self, "Scan Error", f"Failed to scan:\n{result}")
            self.statusBar.showMessage("Scan failed")
            return
        
        self.scan_result = result
        self._populate_table()
        
        self.select_all_btn.setEnabled(True)
        self.deselect_all_btn.setEnabled(True)
        
        count = len(result.jobs)
        self.pairs_count_label.setText(f"{count} pairs")
        self.statusBar.showMessage(f"Found {count} pairs")
        
        # Auto select all
        self._select_all()
    
    def _populate_table(self):
        """Populate table with scan results"""
        self.pairs_table.setRowCount(0)
        
        if not self.scan_result:
            return
        
        jobs = self.scan_result.jobs
        output_root = self.scan_result.output_root
        
        # Check for conflicts
        output_paths = {}
        for i, job in enumerate(jobs):
            out_path = str(output_root / job.output_rel_path)
            if out_path in output_paths:
                output_paths[out_path].append(i)
            else:
                output_paths[out_path] = [i]
        
        conflicts = {path: indices for path, indices in output_paths.items() if len(indices) > 1}
        
        self.pairs_table.setRowCount(len(jobs))
        
        for row, job in enumerate(jobs):
            # Checkbox
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Unchecked)
            self.pairs_table.setItem(row, 0, check_item)
            
            # Base
            base_item = QTableWidgetItem(job.base_path.name)
            base_item.setToolTip(str(job.base_path))
            self.pairs_table.setItem(row, 1, base_item)
            
            # Diff
            diff_item = QTableWidgetItem(job.diff_path.name)
            diff_item.setToolTip(str(job.diff_path))
            self.pairs_table.setItem(row, 2, diff_item)
            
            # Output
            out_path = str(output_root / job.output_rel_path)
            out_item = QTableWidgetItem(str(job.output_rel_path))
            out_item.setToolTip(out_path)
            
            # Check for conflicts
            if out_path in conflicts:
                out_item.setBackground(QColor(255, 200, 200))
                out_item.setToolTip(f"CONFLICT: Multiple pairs output to same file!\n{out_path}")
            elif Path(out_path).exists():
                out_item.setBackground(QColor(255, 255, 200))
                out_item.setToolTip(f"WARNING: File already exists and will be overwritten\n{out_path}")
            
            self.pairs_table.setItem(row, 3, out_item)
            
            # Status
            status_item = QTableWidgetItem("Pending")
            status_item.setForeground(QColor(128, 128, 128))
            self.pairs_table.setItem(row, 4, status_item)
        
        # Connect checkbox changes
        self.pairs_table.itemChanged.connect(self._on_item_changed)
    
    def _on_item_changed(self, item: QTableWidgetItem):
        """Handle table item change"""
        if item.column() == 0:  # Checkbox column
            self._update_process_btn()
    
    def _on_process(self):
        """Handle process button click"""
        selected_jobs = self._get_selected_jobs()
        if not selected_jobs:
            QMessageBox.warning(self, "Error", "No pairs selected.")
            return
        
        # Confirm
        msg = f"Process {len(selected_jobs)} pairs?"
        if QMessageBox.question(self, "Confirm", msg) != QMessageBox.Yes:
            return
        
        # Get settings
        bg_color = None
        if not self.bg_auto_check.isChecked():
            bg_color = self.bg_color_btn.color
        
        # Reset status
        for row in range(self.pairs_table.rowCount()):
            status_item = self.pairs_table.item(row, 4)
            if status_item:
                status_item.setText("Pending")
                status_item.setForeground(QColor(128, 128, 128))
        
        # Start processing
        self.process_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.scan_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(selected_jobs))
        
        self.statusBar.showMessage("Processing...")
        
        self.process_worker = ProcessWorker(
            input_root=self.scan_result.input_root,
            output_root=self.scan_result.output_root,
            jobs=selected_jobs,
            bg_color=bg_color,
            tolerance=self.tolerance_spin.value(),
            bg_mode=self.bg_mode_combo.currentText(),
            align_mode=self.align_combo.currentText(),
            workers=self.workers_spin.value(),
        )
        self.process_worker.progress.connect(self._on_progress)
        self.process_worker.finished.connect(self._on_process_finished)
        self.process_worker.start()
    
    def _on_progress(self, current: int, total: int, message: str):
        """Handle progress update"""
        self.progress_bar.setValue(current)
        self.progress_label.setText(message)
    
    def _on_cancel(self):
        """Handle cancel button click"""
        if self.process_worker:
            self.process_worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.statusBar.showMessage("Cancelling...")
    
    def _on_process_finished(self, result):
        """Handle process completion"""
        self.process_worker = None
        self.cancel_btn.setEnabled(False)
        self.scan_btn.setEnabled(True)
        self._update_process_btn()
        
        if isinstance(result, Exception):
            QMessageBox.critical(self, "Processing Error", f"Failed to process:\n{result}")
            self.statusBar.showMessage("Processing failed")
            return
        
        report: ProcessReport = result
        self._last_report = report
        
        # Update table status
        self._update_table_status(report)
        
        # Show report
        self._show_report(report)
        
        self.export_btn.setEnabled(True)
        self.statusBar.showMessage(
            f"Complete: {report.success_count} success, {report.failed_count} failed, {report.skipped_count} skipped"
        )
    
    def _update_table_status(self, report: ProcessReport):
        """Update table with processing results"""
        # Build lookup by diff path
        results_by_diff = {}
        for item in report.items:
            if item.diff_path:
                results_by_diff[str(item.diff_path)] = item
        
        for row in range(self.pairs_table.rowCount()):
            if row >= len(self.scan_result.jobs):
                continue
            
            job = self.scan_result.jobs[row]
            result = results_by_diff.get(str(job.diff_path))
            
            status_item = self.pairs_table.item(row, 4)
            if not status_item:
                continue
            
            if result is None:
                continue
            
            if result.status == JobStatus.SUCCESS:
                status_item.setText("✓ Success")
                status_item.setForeground(QColor(0, 128, 0))
            elif result.status == JobStatus.FAILED:
                status_item.setText(f"✗ {result.reason.value}")
                status_item.setForeground(QColor(200, 0, 0))
                status_item.setToolTip(result.extra.get("error", ""))
            elif result.status == JobStatus.SKIPPED:
                status_item.setText("⊘ Skipped")
                status_item.setForeground(QColor(128, 128, 0))
    
    def _show_report(self, report: ProcessReport):
        """Show processing report"""
        lines = [
            report.summary(),
            "",
            "=" * 50,
            "Detailed Results:",
            "=" * 50,
        ]
        
        for item in report.items:
            status_str = item.status.value.upper()
            diff_name = item.diff_path.name if item.diff_path else "unknown"
            
            if item.status == JobStatus.SUCCESS and item.align_result:
                ar = item.align_result
                lines.append(
                    f"[{status_str}] {diff_name} - offset=({ar.dx}, {ar.dy}), "
                    f"match={ar.fit_percent:.1f}%, time={item.elapsed_ms:.0f}ms"
                )
            elif item.status == JobStatus.FAILED:
                error = item.extra.get("error", item.reason.value)
                lines.append(f"[{status_str}] {diff_name} - {error}")
            else:
                lines.append(f"[{status_str}] {diff_name} - {item.reason.value}")
        
        self.report_text.setPlainText("\n".join(lines))
    
    def _on_export(self):
        """Export report to JSON"""
        if not hasattr(self, '_last_report'):
            return
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Report", "report.json", "JSON Files (*.json)"
        )
        if not path:
            return
        
        import json
        
        report = self._last_report
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
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Export", f"Report exported to:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")


def run_gui():
    """Run the GUI application"""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
