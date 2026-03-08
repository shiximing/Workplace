import pandas as pd
import sys
import os
import numpy as np
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QCheckBox, QFileDialog, 
                             QScrollArea, QLabel, QMessageBox, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QColorDialog, QDoubleSpinBox, QSplitter, QLineEdit, QGridLayout, QAbstractItemView, QMenu, QTabWidget)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QAction, QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector

# 导入自定义模块
from data_processor import DataProcessor
from ui_components import SummaryDialog

class AccelerationViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.version = "v2.2.0"
        self.setWindowTitle(f"单向台加速度曲线分析工具 ({self.version})")
        self.resize(1350, 900)
        
        self.datasets = {} 
        self.curve_colors = {} 
        self.curve_widths = {} 
        self.curve_scales = {} 
        self.current_selection = None 
        
        self.init_ui()
        
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        
        self.splitter = QSplitter(Qt.Horizontal)
        
        # --- 左侧控制面板 ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMinimumWidth(380) # 再次增加宽度，确保系数输入框可见
        
        self.btn_import = QPushButton(" 导入数据 (文件/文件夹) ▼")
        self.btn_import.setFixedHeight(40)
        self.btn_import.setStyleSheet("font-weight: bold; background-color: #2c3e50; color: white; border-radius: 4px;")
        
        self.import_menu = QMenu(self)
        self.import_menu.addAction("导入数据文件 (支持多选 CSV/FSTRM)", self.import_file)
        self.import_menu.addAction("导入数据文件夹 (扫描 lastresponse)", self.import_folder)
        self.btn_import.setMenu(self.import_menu)
        left_layout.addWidget(self.btn_import)
        
        self.btn_summary = QPushButton("查看横向振动比汇总")
        self.btn_summary.setFixedHeight(40)
        self.btn_summary.setStyleSheet("background-color: #34495e; color: white; border-radius: 4px;")
        self.btn_summary.clicked.connect(self.show_summary_dialog)
        left_layout.addWidget(self.btn_summary)

        left_layout.addWidget(QLabel("\n选择显示曲线:"))
        self.scroll = QScrollArea()
        self.checkbox_container = QWidget()
        self.checkbox_layout = QVBoxLayout(self.checkbox_container)
        self.checkbox_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.checkbox_container)
        self.scroll.setWidgetResizable(True)
        left_layout.addWidget(self.scroll)
        
        self.table = QTableWidget(5, 3) 
        self.table.setHorizontalHeaderLabels(["X向", "Y向", "Z向"])
        self.table.setVerticalHeaderLabels(["平台 MAX", "基座 MAX", "平台-基座", "振动比(未减)", "振动比(减后)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFixedHeight(180)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # 合并振动比行单元格 (跨3列)
        self.table.setSpan(3, 0, 1, 3)
        self.table.setSpan(4, 0, 1, 3)
        left_layout.addWidget(QLabel("详情统计 (单位: g):"))
        left_layout.addWidget(self.table)
        
        # 轴设置
        axis_group = QWidget()
        axis_layout = QVBoxLayout(axis_group)
        self.check_lock_axis = QCheckBox("锁定坐标轴范围")
        self.check_lock_axis.stateChanged.connect(self.on_lock_axis_changed)
        axis_layout.addWidget(self.check_lock_axis)
        
        self.btn_clear_selection = QPushButton("清除选区")
        self.btn_clear_selection.setStyleSheet("background-color: #e74c3c; color: white;")
        self.btn_clear_selection.clicked.connect(self.clear_selection)
        axis_layout.addWidget(self.btn_clear_selection)
        
        xr_layout = QHBoxLayout()
        for lbl, attr in [("X轴:", "xmin"), ("-", "xmax")]:
            xr_layout.addWidget(QLabel(lbl))
            sb = QDoubleSpinBox()
            sb.setRange(-1000, 10000)
            sb.setDecimals(4) # 增加 X 轴精度，方便观察短时间数据
            sb.valueChanged.connect(self.plot_all)
            setattr(self, f"{attr}_input", sb)
            xr_layout.addWidget(sb)
        axis_layout.addLayout(xr_layout)
        
        yr_layout = QHBoxLayout()
        for lbl, attr in [("Y轴:", "ymin"), ("-", "ymax")]:
            yr_layout.addWidget(QLabel(lbl))
            sb = QDoubleSpinBox()
            sb.setRange(-1000, 1000)
            sb.setDecimals(3) # 增加 Y 轴精度
            sb.setValue(-2 if attr == "ymin" else 2)
            sb.valueChanged.connect(self.plot_all)
            setattr(self, f"{attr}_input", sb)
            yr_layout.addWidget(sb)
        axis_layout.addLayout(yr_layout)
        
        left_layout.addWidget(axis_group)
        self.splitter.addWidget(left_panel)
        
        # --- 右侧内容区域 (曲线图) ---
        main_right = QWidget()
        right_layout = QVBoxLayout(main_right)
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        self.toolbar = NavigationToolbar(self.canvas, self)
        # 拦截 Home 按钮点击，回溯到初始状态
        for action in self.toolbar.actions():
            if "home" in (action.text().lower() or action.iconText().lower()):
                action.triggered.disconnect()
                action.triggered.connect(self.reset_home_view)
        self.span = SpanSelector(self.ax, self.on_select, 'horizontal', useblit=True,
                                props=dict(alpha=0.3, facecolor='#3498db'), interactive=False)
        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas)
        self.splitter.addWidget(main_right)
        
        layout.addWidget(self.splitter)
        
        # 记录初始 Y 轴范围
        self.ymin_input.setValue(-15)
        self.ymax_input.setValue(15)
        self.splitter.setSizes([350, 1000])
        layout.addWidget(self.splitter)

    def import_file(self):
        file_paths, _ = QFileDialog.getOpenFileNames(self, "导入数据文件", "", "Data (*.csv *.fstrm)")
        if file_paths:
            self.clear_all_data()
            for path in file_paths:
                # 统一路径格式，防止 Windows 下大小写或斜杠不一致导致的 KeyError
                path = os.path.normcase(os.path.normpath(path))
                try:
                    df, interval = DataProcessor.parse_fstrm(path) if path.lower().endswith('.fstrm') else DataProcessor.parse_csv(path)
                    self.datasets[path] = {"data": df, "interval": interval, "display_name": os.path.basename(path)}
                    self.post_process_dataset(path)
                except Exception as e: QMessageBox.critical(self, "导入失败", str(e))
            self.update_checkboxes()
            self.plot_all()

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择数据文件夹")
        if not folder: return
        self.setWindowTitle(f"单向台分析 - {os.path.basename(folder)} ({self.version})")
        self.clear_all_data()
        
        found = False
        import re
        hz_pattern = re.compile(r"(\d+)HZ", re.IGNORECASE)
        
        for root, dirs, files in os.walk(folder):
            for file in files:
                ext = file.lower()
                path = os.path.normcase(os.path.normpath(os.path.join(root, file)))
                
                # 策略 1: 扫描 lastresponse.fstrm (实验结果)
                if file == "lastresponse.fstrm":
                    try:
                        df, interval = DataProcessor.parse_fstrm(path)
                        rel = os.path.relpath(root, folder)
                        name = os.path.basename(folder) if rel == "." else rel
                        self.datasets[path] = {"data": df, "interval": interval, "display_name": name, "is_command": False}
                        self.post_process_dataset(path)
                        found = True
                    except: pass
                
                # 策略 2: 扫描命令所在的 CSV (目标曲线)
                elif ext.endswith(".csv"):
                    # 如果路径包含“命令”或“cmd”，或者文件名包含“target”
                    u_path = path.upper()
                    is_cmd = "命令" in u_path or "CMD" in u_path or "TARGET" in u_path or "目标" in u_path
                    try:
                        df, interval = DataProcessor.parse_csv(path)
                        rel = os.path.relpath(root, folder)
                        # 用户要求：命令文件夹名字改成导入csv文件的父文件夹名字
                        if is_cmd:
                            group_name = os.path.basename(root)
                        else:
                            group_name = os.path.basename(folder) if rel == "." else rel
                            
                        self.datasets[path] = {
                            "data": df, "interval": interval, 
                            "display_name": group_name, 
                            "is_command": is_cmd,
                            "file_label": file
                        }
                        self.post_process_dataset(path)
                        found = True
                    except: pass
                    
        if not found: QMessageBox.warning(self, "提示", "未找到有效的实验数据 (.fstrm) 或命令文件 (.csv)")
        
        if self.datasets:
            # 初始范围设置：优先找非命令的第一个数据集
            ref_path = next((p for p, info in self.datasets.items() if not info.get('is_command')), list(self.datasets.keys())[0])
            ds = self.datasets[ref_path]
            pcX = ds["p_cols"]["X"]
            if pcX:
                v_max = np.abs(ds["data"][pcX]).max()
                margin = v_max * 0.2 if v_max > 0 else 2.0
                limit = np.ceil(v_max + margin)
                self.ymin_input.setValue(-limit)
                self.ymax_input.setValue(limit)

        self.update_checkboxes()
        self.plot_all()

    def clear_all_data(self):
        self.datasets = {}
        self.curve_colors = {}
        self.curve_widths = {}
        self.curve_scales = {}

    def post_process_dataset(self, path):
        path = os.path.normcase(os.path.normpath(path))
        info = self.datasets[path]
        df = info["data"]
        is_cmd_file = info.get("is_command", False)
        
        p_cols, b_cols = {"X":None,"Y":None,"Z":None}, {"X":None,"Y":None,"Z":None}
        
        for col in df.columns:
            u_c = col.upper().replace("_", " ").replace("-", " ")
            
            # 如果是命令文件，不再排除 COMMANDED 等，因为我们要看目标数据
            if not is_cmd_file:
                if any(k in u_c for k in ["UNFILTERED", "COMMANDED", "FEEDBACK", "PILOT", "ERROR", "OFFSET", "TARGET", "目标"]):
                    continue
            
            is_platform = "PLATFORM" in u_c or "平台" in u_c
            is_base = "BASE" in u_c or "基座" in u_c or "底座" in u_c
            # 如果是命令文件，其 X 轴通常标记为 target x 或 x_platform 等
            is_target = "TARGET" in u_c or "目标" in u_c or "COMMAND" in u_c
            
            axis = None
            if " X " in f" {u_c} " or u_c.startswith("X ") or u_c.endswith(" X") or "X向" in u_c: axis = "X"
            elif " Y " in f" {u_c} " or u_c.startswith("Y ") or u_c.endswith(" Y") or "Y向" in u_c: axis = "Y"
            elif " Z " in f" {u_c} " or u_c.startswith("Z ") or u_c.endswith(" Z") or "Z向" in u_c: axis = "Z"
            
            if axis:
                if is_platform:
                    if p_cols[axis] is None or len(col) < len(p_cols[axis]):
                        p_cols[axis] = col
                elif is_base:
                    if b_cols[axis] is None or len(col) < len(b_cols[axis]):
                        b_cols[axis] = col
                elif is_cmd_file and is_target:
                    # 优先把 target 映射到平台位置显示（为了计算或对比方）
                    if p_cols[axis] is None:
                        p_cols[axis] = col
                    
        self.datasets[path].update({"p_cols": p_cols, "b_cols": b_cols, 
                                    "time_col": next((c for c in df.columns if "Time" in c), df.columns[-1])})
        self.calculate_stats(path)

    def calculate_stats(self, path):
        path = os.path.normcase(os.path.normpath(path))
        if path not in self.datasets: return
        ds = self.datasets[path]
        df = ds["data"]
        t_col = ds["time_col"]
        
        # 确定统计范围逻辑升级：
        # 1. 如果锁定了坐标轴，始终以手动输入框的数值为准（圈选也会同步更新这些框）
        # 2. 如果没锁定但有选区，以选区为准
        # 3. 否则全量
        t_start, t_end = df[t_col].min(), df[t_col].max()
        if self.check_lock_axis.isChecked():
            t_start, t_end = self.xmin_input.value(), self.xmax_input.value()
        elif self.current_selection:
            t_start, t_end = self.current_selection
            
        sub = df[(df[t_col] >= t_start) & (df[t_col] <= t_end)]
        if len(sub) == 0: 
            # 如果当前范围内没数据，不更新表格但也不要让它卡住
            return
        
        max_v = {}
        for ax in ["X","Y","Z"]:
            pc, bc = ds["p_cols"][ax], ds["b_cols"][ax]
            # 获取当前缩放系数
            key_p = f"{pc}_{path}" if pc else None
            scale_p = self.curve_scales.get(key_p, 1.0) if key_p else 1.0
            key_b = f"{bc}_{path}" if bc else None
            scale_b = self.curve_scales.get(key_b, 1.0) if key_b else 1.0
            
            # 计算该范围内的峰值
            p_data = sub[pc].values if pc else np.zeros(1)
            b_data = sub[bc].values if bc else np.zeros(1)
            max_v[ax+"_P"] = np.abs(p_data).max() * scale_p
            max_v[ax+"_B"] = np.abs(b_data).max() * scale_b
        
        # 计算比例
        ds["ratio_unsub"] = 0; ds["ratio_sub"] = 0
        x_p = max_v["X_P"]
        if x_p > 0:
            ds["ratio_unsub"] = (max_v["Y_P"]**2 + max_v["Z_P"]**2)**0.5 / x_p
            dx = x_p - max_v["X_B"]
            if dx > 1e-4:
                dy, dz = max_v["Y_P"] - max_v["Y_B"], max_v["Z_P"] - max_v["Z_B"]
                ds["ratio_sub"] = (dy**2 + dz**2)**0.5 / dx
            
        # 填充表格
        for i, ax in enumerate(["X","Y","Z"]):
            self.table.setItem(0, i, QTableWidgetItem(f"{max_v[ax+'_P']:.4f}"))
            self.table.setItem(1, i, QTableWidgetItem(f"{max_v[ax+'_B']:.4f}"))
            self.table.setItem(2, i, QTableWidgetItem(f"{max_v[ax+'_P']-max_v[ax+'_B']:.4f}"))
        
        # 振动比 (显示在合并后的单元格)
        self.table.setItem(3, 0, QTableWidgetItem(f"{ds['ratio_unsub']*100:.2f}%"))
        self.table.setItem(4, 0, QTableWidgetItem(f"{ds['ratio_sub']*100:.2f}%"))
        # 居中显示
        self.table.item(3, 0).setTextAlignment(Qt.AlignCenter)
        self.table.item(4, 0).setTextAlignment(Qt.AlignCenter)
            
    def update_checkboxes(self):
        while self.checkbox_layout.count():
            w = self.checkbox_layout.takeAt(0).widget()
            if w: w.deleteLater()
        
        # 1. 频率分组逻辑：支持按 (是否命令, 显示名) 分组
        groups = {} # { (is_cmd, name): [paths] }
        for path, info in self.datasets.items():
            is_cmd = info.get('is_command', False)
            name = info.get('display_name', 'Unknown')
            key = (is_cmd, name)
            if key not in groups: groups[key] = []
            groups[key].append(path)
            
        import re
        # 匹配频率：寻找数字+Hz，或者首个出现的数字
        hz_pattern = re.compile(r"(\d+)(?:Hz|HZ|hz)?")
        def get_hz_val(key_tuple):
            name = key_tuple[1]
            match = hz_pattern.search(name)
            return int(match.group(1)) if match else 9999

        # 排序策略：响应在前，命令在后；组间按频率数值升序 (70Hz -> 200Hz)
        sorted_keys = sorted(groups.keys(), key=lambda k: (1 if k[0] else 0, get_hz_val(k)))
        
        pal = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        idx = 0
        group_idx = 0
        
        for key in sorted_keys:
            is_cmd_group, group_name = key
            # --- 创建可折叠分组头 ---
            display_title = group_name if not is_cmd_group else f"目标命令: {group_name}"
            group_header = QPushButton(f"▼ {display_title}")
            group_header.setStyleSheet(f"""
                QPushButton {{ text-align: left; font-weight: bold; 
                             color: {"#c0392b" if is_cmd_group else "#2c3e50"}; 
                             background-color: {"#fadbd8" if is_cmd_group else "#ecf0f1"}; 
                             border: none; padding: 6px; border-radius: 3px; }}
                QPushButton:hover {{ background-color: {"#f5b7b1" if is_cmd_group else "#dcdde1"}; }}
            """)
            self.checkbox_layout.addWidget(group_header)
            
            group_container = QWidget()
            group_vbox = QVBoxLayout(group_container)
            group_vbox.setContentsMargins(15, 2, 0, 8) 
            group_vbox.setSpacing(2)
            
            def toggle_group(checked=False, c=group_container, h=group_header, title=display_title):
                is_visible = c.isVisible()
                c.setVisible(not is_visible)
                h.setText(f"{'▲' if is_visible else '▼'} {title}")
            group_header.clicked.connect(toggle_group)
            
            # 分组内文件排序：数值型排序 (保证 70Hz 在 100Hz 之前)
            paths_in_group = sorted(groups[key], key=lambda p: get_hz_val((0, os.path.basename(p))))
            
            for path in paths_in_group:
                info = self.datasets[path]
                is_cmd_file = info.get('is_command', False)
                df = info["data"]
                
                # 筛选要显示的列
                cols = []
                for c in df.columns:
                    u_c = c.upper()
                    if 'TIME' in u_c: continue
                    # 包含关键字：加速度、平台、基座、命令或目标
                    includes = ['[G]', 'ACCELERATION', 'PLATFORM', 'BASE', 'COMMAND', 'TARGET', '平台', '基座', '命令', '目标']
                    # 排除关键字
                    excludes = ['FEEDBACK', 'ERROR', 'OFFSET', 'PILOT']
                    # 用户要求：FSTRM (响应数据) 不需要显示 Target 数据
                    if not is_cmd_file: 
                        excludes.extend(['COMMANDED', 'TARGET', '目标'])
                    
                    if any(k in u_c for k in includes):
                        if not any(k in u_c for k in excludes):
                            cols.append(c)

                def sort_key(c):
                    u = c.upper()
                    if 'PLATFORM' in u or '平台' in u: return 0
                    if 'BASE' in u or '基座' in u or '底座' in u: return 1
                    if 'TARGET' in u or '目标' in u: return 9 
                    if 'COMMAND' in u or '命令' in u: return 10
                    return 2
                
                for col in sorted(cols, key=sort_key):
                    w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(2,1,2,1); l.setSpacing(6)
                    
                    display_col_name = col
                    if is_cmd_file:
                        # 如果是命令文件曲线，增加文件标识以便区分
                        f_lbl = info.get('file_label', '')
                        display_col_name = f"[命令] {col}" if not f_lbl else f"[命令] {col} ({f_lbl})"
                    
                    cb = QCheckBox(display_col_name); cb.setProperty("path", path); cb.setProperty("col", col)
                    cb.setMinimumWidth(180)
                    # 用户要求：目标命令曲线默认不要勾选。只勾选首个响应组的首个曲线。
                    cb.setChecked(group_idx == 0 and idx == 0 and not is_cmd_group)
                    cb.stateChanged.connect(self.plot_all)
                    l.addWidget(cb)
                    l.addStretch()
                    
                    c_key = f"{col}_{path}"
                    if c_key not in self.curve_colors:
                        self.curve_colors[c_key] = pal[idx % len(pal)]
                        self.curve_scales[c_key] = 1.0
                        self.curve_widths[c_key] = 1.0 if is_cmd_file else 1.5
                    
                    btn_color = QPushButton()
                    btn_color.setFixedSize(18, 18)
                    btn_color.setStyleSheet(f"background-color: {self.curve_colors[c_key]}; border: 1px solid #999; border-radius: 2px;")
                    # 修复：明确传递按钮对象，确保 sender 识别正确
                    btn_color.clicked.connect(lambda checked=False, k=c_key, b=btn_color: self.choose_color(k, b))
                    l.addWidget(btn_color)
                    
                    sb_width = QDoubleSpinBox()
                    sb_width.setRange(0.5, 10.0); sb_width.setSingleStep(0.5); sb_width.setValue(self.curve_widths[c_key]); sb_width.setFixedWidth(50)
                    sb_width.valueChanged.connect(lambda v, k=c_key: self.update_curve_setting(k, 'width', v))
                    l.addWidget(sb_width)

                    l.addWidget(QLabel("系"))
                    edit_scale = QLineEdit(f"{self.curve_scales[c_key]:.2f}"); edit_scale.setFixedWidth(40); edit_scale.setAlignment(Qt.AlignCenter)
                    edit_scale.textChanged.connect(lambda v, k=c_key: self.update_curve_scale_text(k, v))
                    l.addWidget(edit_scale)
                    
                    group_vbox.addWidget(w)
                    idx += 1
            
            self.checkbox_layout.addWidget(group_container)
            is_collapsed = (group_idx > 0)
            group_container.setVisible(not is_collapsed)
            group_header.setText(f"{'▲' if is_collapsed else '▼'} {display_title}")
            group_idx += 1

    def plot_all(self):
        self.ax.clear()
        active_path = None
        has = False
        
        # 多文件勾选时，统计逻辑应优先服务于非命令文件
        selected_paths = []
        for i in range(self.checkbox_layout.count()):
            w = self.checkbox_layout.itemAt(i).widget()
            if not w: continue
            checkboxes = w.findChildren(QCheckBox)
            for cb in checkboxes:
                if cb.isChecked():
                    p = os.path.normcase(os.path.normpath(cb.property("path")))
                    c = cb.property("col")
                    if p not in self.datasets: continue
                    selected_paths.append((p, c))
                    
                    ds = self.datasets[p]
                    c_key = f"{c}_{p}"
                    scale = self.curve_scales.get(c_key, 1.0)
                    width = self.curve_widths.get(c_key, 1.5)
                    color = self.curve_colors.get(c_key, "#1f77b4")
                    
                    lbl = f"{c} ({ds['display_name']})"
                    if ds.get('is_command'):
                        f_lbl = ds.get('file_label', '')
                        lbl = f"[命令] {c} ({f_lbl or ds['display_name']})"
                    
                    self.ax.plot(ds["data"][ds["time_col"]], ds["data"][c] * scale, 
                                 label=lbl, color=color, linewidth=width)
                    has = True

        # 确定统计基准文件：优先选择已勾选的响应数据 (.fstrm)
        if selected_paths:
            priority_path = None
            for p, c in selected_paths:
                if not self.datasets[p].get('is_command'):
                    priority_path = p
                    break
            active_path = priority_path or selected_paths[0][0]
            self.calculate_stats(active_path)
            
        if has: 
            self.ax.legend(loc='upper right', fontsize='x-small')
            if not self.check_lock_axis.isChecked():
                curr_ymin, curr_ymax = self.ax.get_ylim()
                abs_max = max(abs(curr_ymin), abs(curr_ymax))
                margin = abs_max * 0.1 if abs_max > 0 else 0.5
                limit = abs_max + margin
                self.ax.set_ylim(-limit, limit)
            self.ax.axhline(0, color='black', linewidth=1, alpha=0.3, linestyle='--')
        
        if self.check_lock_axis.isChecked():
            self.ax.set_xlim(self.xmin_input.value(), self.xmax_input.value())
            self.ax.set_ylim(self.ymin_input.value(), self.ymax_input.value())
        elif self.current_selection:
            self.ax.set_xlim(self.current_selection[0], self.current_selection[1])
            self.ax.autoscale(axis='y')

        self.ax.grid(True, linestyle='--', alpha=0.5)
        self.canvas.draw()

    def on_lock_axis_changed(self): self.plot_all()
    def clear_selection(self): self.current_selection = None; self.plot_all()
    
    def reset_home_view(self):
        self.current_selection = None
        self.check_lock_axis.blockSignals(True)
        self.check_lock_axis.setChecked(False)
        self.check_lock_axis.blockSignals(False)
        self.plot_all()
        # 让 toolbar 内部也重置（如果它记录了视图历史）
        self.toolbar.home()

    def on_select(self, xmin, xmax):
        if abs(xmax - xmin) < 1e-7: # 防止点击误触发导致选区失效
            return
        self.current_selection = (xmin, xmax)
        # 圈选后同步更新手动坐标轴数值
        self.xmin_input.blockSignals(True)
        self.xmax_input.blockSignals(True)
        self.xmin_input.setValue(xmin)
        self.xmax_input.setValue(xmax)
        self.xmin_input.blockSignals(False)
        self.xmax_input.blockSignals(False)
        self.plot_all()
    
    def choose_color(self, key, btn):
        if not btn: return
        color = QColorDialog.getColor(QColor(self.curve_colors[key]), self)
        if color.isValid():
            hex_color = color.name()
            self.curve_colors[key] = hex_color
            btn.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #999; border-radius: 2px;")
            self.plot_all()

    def update_curve_scale_text(self, key, text):
        try:
            self.curve_scales[key] = float(text)
            self.plot_all()
        except: pass

    def update_curve_setting(self, key, setting, value):
        try:
            val = float(value)
            if setting == 'width': self.curve_widths[key] = val
            self.plot_all()
        except: pass

    def show_summary_dialog(self): SummaryDialog(self.datasets, self).exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 10))
    window = AccelerationViewer()
    window.show()
    sys.exit(app.exec())
