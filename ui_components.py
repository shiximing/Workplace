import os
import re
import numpy as np
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QTableWidget, QTableWidgetItem, QHeaderView, 
                             QDialog, QLineEdit, QComboBox, QDoubleSpinBox, QCheckBox,
                             QGridLayout, QFrame, QApplication, QMessageBox)
from PySide6.QtCore import Qt, QMimeData
from PySide6.QtGui import QFont, QColor
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter
from matplotlib.widgets import SpanSelector
import matplotlib.pyplot as plt

# 配置 Matplotlib 中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

try:
    from scipy.interpolate import PchipInterpolator
except ImportError:
    PchipInterpolator = None

class SummaryDialog(QDialog):
    def __init__(self, datasets, parent=None):
        super().__init__(parent)
        self.setWindowTitle("横向振动比汇总")
        self.resize(1000, 600)
        self.datasets = datasets
        self.init_ui()
        self.fill_data()
        self.plot_chart()

    def init_ui(self):
        layout = QVBoxLayout(self)
        content_layout = QHBoxLayout()
        
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["序号(可改)", "试验名称", "振动比(未减) (%)", "振动比(减后) (%)", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self.on_item_changed)
        content_layout.addWidget(self.table, 1)
        
        self.figure = Figure(figsize=(5, 4), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        content_layout.addWidget(self.canvas, 1)
        layout.addLayout(content_layout)
        
        attr_layout = QHBoxLayout()
        attr_layout.addWidget(QLabel("X轴名称:"))
        self.xlab_input = QLineEdit("自定义标签")
        self.xlab_input.textChanged.connect(self.plot_chart)
        attr_layout.addWidget(self.xlab_input)
        
        attr_layout.addWidget(QLabel("Y轴名称:"))
        self.ylab_input = QLineEdit("振动比 (%)")
        self.ylab_input.textChanged.connect(self.plot_chart)
        attr_layout.addWidget(self.ylab_input)
        
        attr_layout.addWidget(QLabel("图表类型:"))
        self.chart_type = QComboBox()
        self.chart_type.addItems(["柱状图", "带平滑线的散点图"])
        self.chart_type.currentIndexChanged.connect(self.plot_chart)
        attr_layout.addWidget(self.chart_type)
        layout.addLayout(attr_layout)
        
        range_layout = QHBoxLayout()
        self.check_lock_axis = QCheckBox("锁定坐标轴")
        self.check_lock_axis.stateChanged.connect(self.plot_chart)
        range_layout.addWidget(self.check_lock_axis)
        
        for lbl, attr in [("X轴:", "xmin"), ("-", "xmax"), ("Y轴范围(%):", "ymin"), ("-", "ymax")]:
            range_layout.addWidget(QLabel(lbl))
            sb = QDoubleSpinBox()
            sb.setRange(-10000, 10000)
            if 'y' in attr: sb.setRange(-100, 1000)
            sb.setValue(150 if attr == "xmax" else (100 if attr == "ymax" else 0))
            sb.valueChanged.connect(self.plot_chart)
            setattr(self, f"{attr}_input", sb)
            range_layout.addWidget(sb)
        layout.addLayout(range_layout)
        
        btn_layout = QHBoxLayout()
        for text, color, func in [("复制为 Excel 格式", "#2ecc71", self.copy_for_excel), 
                                ("复制为 Word 表格", "#3498db", self.copy_for_word),
                                ("关闭", None, self.accept)]:
            btn = QPushButton(text)
            btn.setFixedHeight(35)
            if color: btn.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;")
            btn.clicked.connect(func)
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)

    def fill_data(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        hz_pattern = re.compile(r"(\d+)Hz", re.IGNORECASE)
        seen_names = set()
        for i, (path, info) in enumerate(self.datasets.items(), 1):
            if info.get("is_command"): continue
            display_name = info.get("display_name", os.path.basename(path))
            if display_name in seen_names: continue
            seen_names.add(display_name)
            
            row = self.table.rowCount()
            self.table.insertRow(row)
            hz_match = hz_pattern.search(display_name)
            seq_val = float(hz_match.group(1)) if hz_match else float(i)
            
            item_seq = QTableWidgetItem()
            item_seq.setData(Qt.EditRole, seq_val)
            self.table.setItem(row, 0, item_seq)
            
            self.table.setItem(row, 1, QTableWidgetItem(display_name))
            
            for col, key in [(2, "ratio_unsub"), (3, "ratio_sub")]:
                val = info.get(key)
                text = f"{val*100:.2f}" if val is not None else "N/A"
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

            btn_delete = QPushButton("删除")
            btn_delete.setStyleSheet("background-color: #e74c3c; color: white; padding: 2px;")
            btn_delete.clicked.connect(lambda checked, p=path: self.delete_item(p))
            self.table.setCellWidget(row, 4, btn_delete)
        self.table.sortItems(0, Qt.AscendingOrder)
        self.table.blockSignals(False)

    def on_item_changed(self, item):
        if item.column() == 0:
            self.table.blockSignals(True)
            try: item.setData(Qt.EditRole, float(item.text()))
            except: pass
            self.table.sortItems(0, Qt.AscendingOrder)
            self.table.blockSignals(False)
        self.plot_chart()

    def delete_item(self, path):
        if path in self.datasets:
            del self.datasets[path]
            if self.parent():
                self.parent().update_checkboxes()
                self.parent().plot_all()
            self.fill_data()
            self.plot_chart()

    def plot_chart(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        labels, r1, r2 = [], [], []
        for r in range(self.table.rowCount()):
            labels.append(self.table.item(r, 0).text())
            try: r1.append(float(self.table.item(r, 2).text()))
            except: r1.append(0)
            try: r2.append(float(self.table.item(r, 3).text()))
            except: r2.append(0)
        
        if not labels: return
        try:
            x_vals = np.array([float(l) for l in labels])
            is_numeric = True
        except:
            x_vals = np.arange(len(labels))
            is_numeric = False

        if self.chart_type.currentText() == "柱状图":
            # 柱状图：确保计算间距时排除重复点
            diffs = np.diff(np.sort(x_vals))
            valid_diffs = diffs[diffs > 0]
            width = (np.min(valid_diffs) * 0.35) if is_numeric and len(valid_diffs) > 0 else 0.5
            
            b1 = ax.bar(x_vals - width/2, r1, width, label='未减基座', color='#3498db', alpha=0.8)
            b2 = ax.bar(x_vals + width/2, r2, width, label='减基座后', color='#e67e22', alpha=0.8)
            ax.bar_label(b1, fmt='%.1f%%', padding=3, fontsize=8, color='#0a5a9c')
            ax.bar_label(b2, fmt='%.1f%%', padding=3, fontsize=8, color='#a04a00')
            ax.set_xticks(x_vals)
            ax.set_xticklabels(labels)
        else:
            # 带平滑线的散点图
            # 修复 ValueError: x must be strictly increasing sequence
            if len(x_vals) > 2 and PchipInterpolator and is_numeric:
                # 即使 fill_data 做了去重，手动编辑表格仍可能产生重复频率
                x_unique, indices = np.unique(x_vals, return_index=True)
                r1_unique = np.array(r1)[indices]
                r2_unique = np.array(r2)[indices]
                
                if len(x_unique) > 2:
                    x_new = np.linspace(x_unique.min(), x_unique.max(), 300)
                    interp1 = PchipInterpolator(x_unique, r1_unique)
                    ax.plot(x_new, interp1(x_new), '-', color='#3498db', linewidth=2, label='未减基座')
                    interp2 = PchipInterpolator(x_unique, r2_unique)
                    ax.plot(x_new, interp2(x_new), '-', color='#e67e22', linewidth=2, label='减基座后')
                else:
                    ax.plot(x_vals, r1, '-', color='#3498db', linewidth=2, label='未减基座')
                    ax.plot(x_vals, r2, '-', color='#e67e22', linewidth=2, label='减基座后')
            else:
                ax.plot(x_vals, r1, '-', color='#3498db', linewidth=2, label='未减基座')
                ax.plot(x_vals, r2, '-', color='#e67e22', linewidth=2, label='减基座后')
            
            # 画点并添加数据标签
            ax.scatter(x_vals, r1, color='#3498db', zorder=5)
            ax.scatter(x_vals, r2, color='#e67e22', zorder=5)
            
            for i, txt in enumerate(r1):
                ax.annotate(f"{txt:.1f}%", (x_vals[i], r1[i]), textcoords="offset points", 
                            xytext=(0,10), ha='center', fontsize=8, color='#0a5a9c')
            for i, txt in enumerate(r2):
                ax.annotate(f"{txt:.1f}%", (x_vals[i], r2[i]), textcoords="offset points", 
                            xytext=(0,-15), ha='center', fontsize=8, color='#a04a00')

        ax.yaxis.set_major_formatter(PercentFormatter())
        ax.set_ylabel(self.ylab_input.text())
        ax.set_xlabel(self.xlab_input.text())
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)
        if self.check_lock_axis.isChecked():
            ax.set_xlim(self.xmin_input.value(), self.xmax_input.value())
            ax.set_ylim(self.ymin_input.value(), self.ymax_input.value())
        self.canvas.draw()

    def copy_for_excel(self):
        text = ""
        # 复制表头
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount() - 1)]
        text += "\t".join(headers) + "\n"
        # 复制内容
        for r in range(self.table.rowCount()):
            text += "\t".join([self.table.item(r, c).text() for c in range(self.table.columnCount() - 1)]) + "\n"
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "成功", "汇总数据已按 Excel 格式复制到剪贴板。")

    def copy_for_word(self):
        # 使用 HTML 格式复制表格，这样粘贴到 Word 会保持表格样式
        html = "<table border='1' style='border-collapse: collapse;'>"
        # 表头
        html += "<tr style='background-color: #f2f2f2;'>"
        for c in range(self.table.columnCount() - 1):
            html += f"<th>{self.table.horizontalHeaderItem(c).text()}</th>"
        html += "</tr>"
        # 内容
        for r in range(self.table.rowCount()):
            html += "<tr>"
            for c in range(self.table.columnCount() - 1):
                val = self.table.item(r, c).text()
                html += f"<td>{val}</td>"
            html += "</tr>"
        html += "</table>"
        
        mime = QMimeData()
        mime.setHtml(html)
        # 同时提供纯文本备选方案
        text = ""
        for r in range(self.table.rowCount()):
            text += " | ".join([self.table.item(r, c).text() for c in range(self.table.columnCount() - 1)]) + "\n"
        mime.setText(text)
        
        QApplication.clipboard().setMimeData(mime)
        QMessageBox.information(self, "成功", "汇总数据已按 Word 表格格式复制到剪贴板。")

class FFTPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        header = QHBoxLayout()
        header.addWidget(QLabel("分析频率范围 (Hz):"))
        self.f_min = QDoubleSpinBox()
        self.f_min.setRange(0, 1000)
        self.f_min.setValue(0)
        header.addWidget(self.f_min)
        header.addWidget(QLabel("-"))
        self.f_max = QDoubleSpinBox()
        self.f_max.setRange(0, 5000)
        self.f_max.setValue(500)
        header.addWidget(self.f_max)
        
        self.btn_update = QPushButton("分析选区段 FFT/PSD")
        self.btn_update.setStyleSheet("background-color: #e67e22; color: white; font-weight: bold;")
        header.addWidget(self.btn_update)
        header.addStretch()
        layout.addLayout(header)

        # 添加时域原始曲线图 (在上方)
        self.fig_time = Figure(figsize=(10, 2.5), tight_layout=True)
        self.canvas_time = FigureCanvas(self.fig_time)
        self.ax_time = self.fig_time.add_subplot(111)
        self.ax_time.set_title("原始曲线 (选区截取)")
        self.ax_time.grid(True, linestyle='--', alpha=0.5)
        # 在频谱页也添加选区功能
        self.span = SpanSelector(self.ax_time, self.on_time_select, 'horizontal', useblit=True,
                                props=dict(alpha=0.3, facecolor='#3498db'), interactive=False)
        layout.addWidget(self.canvas_time)
        
        grid = QGridLayout()
        self.figures = []
        self.canvases = []
        titles = ["X向 FFT (幅值)", "Z向 FFT (幅值)", "X向 PSD (g²/Hz)", "Z向 PSD (g²/Hz)"]
        
        for i in range(4):
            fig = Figure(tight_layout=True)
            canvas = FigureCanvas(fig)
            ax = fig.add_subplot(111)
            ax.set_title(titles[i])
            ax.grid(True, linestyle='--', alpha=0.5)
            grid.addWidget(canvas, i // 2, i % 2)
            self.figures.append(fig)
            self.canvases.append(canvas)
            
        layout.addLayout(grid)

    def on_time_select(self, xmin, xmax):
        # 此回调可供外部(AccelerationViewer)更新
        if hasattr(self, 'on_select_callback'):
            self.on_select_callback(xmin, xmax)

    def update_plots(self, x_fft_list, z_fft_list, x_psd_list, z_psd_list, time_data_list=None):
        """
        x_fft_list: list of (freq, vals, label, color)
        time_data_list: list of (time, data, label, color)
        """
        # 更新时域图
        if time_data_list:
            self.ax_time.clear()
            for t, d, label, color in time_data_list:
                self.ax_time.plot(t, d, label=label, color=color, alpha=0.9, linewidth=1)
            self.ax_time.legend(loc='upper right', fontsize='xx-small')
            self.ax_time.grid(True, linestyle='--', alpha=0.5)
            self.ax_time.set_title("原始曲线 (选区截取)")
            self.canvas_time.draw()

        data_lists = [x_fft_list, z_fft_list, x_psd_list, z_psd_list]
        f_min, f_max = self.f_min.value(), self.f_max.value()
        
        titles = ["X向 FFT", "Z向 FFT", "X向 PSD", "Z向 PSD"]
        
        for i, group in enumerate(data_lists):
            ax = self.figures[i].axes[0]
            ax.clear()
            
            for freq, vals, label, color in group:
                if len(freq) > 0:
                    ax.plot(freq, vals, label=label, color=color, alpha=0.8)
            
            ax.set_xlim(f_min, f_max)
            ax.grid(True, linestyle='--', alpha=0.5)
            ax.set_title(titles[i])
            if len(group) > 1: # 仅在有多条曲线时显示图例
                ax.legend(loc='upper right', fontsize='x-small')
            self.canvases[i].draw()
