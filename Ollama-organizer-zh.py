import sys
import os
import json
import shutil
import time
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, \
    QListWidget, QListWidgetItem, QAbstractItemView, QFileDialog, QLineEdit, QSizePolicy, QTextEdit, QMessageBox
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QRect
from PyQt5.QtGui import QFont

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
MAX_THREADS = 3

def make_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def copy_model_files_and_verify(model_name, model_version, root_dir_Ollama_new, root_dir_Ollama, blobs_dir_cache):
    try:
        root_dir_models = os.path.join(root_dir_Ollama, 'models')
        manifests_dir = os.path.join(root_dir_models, f'manifests/registry.ollama.ai/library/{model_name}')
        model_offer_rel_dir = f'manifests/registry.ollama.ai/library/{model_name}'
        root_dir_new_models = os.path.join(root_dir_Ollama_new, model_version, 'models')
        blobs_dir_new = os.path.join(root_dir_new_models, 'blobs')
        model_dir_new = os.path.join(root_dir_new_models, model_offer_rel_dir)
        model_config_path = os.path.join(manifests_dir, model_version)
        model_config_path_new = os.path.join(model_dir_new, model_version)
        make_dir(model_dir_new)
        make_dir(blobs_dir_new)
        shutil.copy(model_config_path, model_config_path_new)
        with open(model_config_path, 'r', encoding='utf-8') as f:
            content = json.load(f)
        config_digest = content['config']['digest'].replace('sha256:', 'sha256-')
        digest_src = os.path.join(blobs_dir_cache, config_digest)
        digest_dst = os.path.join(blobs_dir_new, config_digest)
        shutil.copy(digest_src, digest_dst)
        if not os.path.exists(digest_dst):
            raise RuntimeError(f"缺失 config digest 文件：{digest_dst}")
        layer_digests = []
        for layer in content['layers']:
            digest = layer['digest'].replace('sha256:', 'sha256-')
            src = os.path.join(blobs_dir_cache, digest)
            dst = os.path.join(blobs_dir_new, digest)
            shutil.copy(src, dst)
            if not os.path.exists(dst):
                raise RuntimeError(f"缺失 layer digest 文件：{dst}")
            layer_digests.append(layer['digest'])
        return True, config_digest, layer_digests
    except Exception as e:
        return False, f"{model_name}/{model_version} -> {e}", None

class WorkerSignals(QObject):
    progress = pyqtSignal(str)
    result = pyqtSignal(dict)
    finished = pyqtSignal()

class OrganizeThread(QThread):
    def __init__(self, tasks, root_dir_Ollama, root_dir_Ollama_new, processed_record_file, error_log_file):
        super().__init__()
        self.tasks = tasks
        self.root_dir_Ollama = root_dir_Ollama
        self.root_dir_Ollama_new = root_dir_Ollama_new
        self.processed_record_file = processed_record_file
        self.error_log_file = error_log_file
        self.signals = WorkerSignals()

    def run(self):
        processed_records = {}
        if os.path.exists(self.processed_record_file):
            with open(self.processed_record_file, 'r', encoding='utf-8') as f:
                processed_records = json.load(f)
        blobs_dir_cache = os.path.join(self.root_dir_Ollama, 'models', 'blobs')

        success_models = 0
        failed_models = 0
        total_digests = 0
        failed_list = []
        total_models = len(self.tasks)
        skipped_models = 0

        start_time = time.time()
        self.signals.progress.emit(f"本次任务总共 {total_models} 个模型版本\n")

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = {}
            for model_name, model_version in self.tasks:
                if model_name in processed_records and model_version in processed_records[model_name]:
                    skipped_models += 1
                    msg = f"[跳过] 模型：{model_name} 版本：{model_version}"
                    self.signals.progress.emit(msg)
                    continue
                processed_records.setdefault(model_name, {})
                new_model_dir = os.path.join(self.root_dir_Ollama_new, model_name)
                future = executor.submit(
                    copy_model_files_and_verify,
                    model_name, model_version,
                    new_model_dir, self.root_dir_Ollama,
                    blobs_dir_cache
                )
                futures[future] = (model_name, model_version)

            finished_count = skipped_models
            for future in as_completed(futures):
                model_name, model_version = futures[future]
                try:
                    success, result, layers = future.result()
                    if success:
                        processed_records[model_name][model_version] = {
                            "config_digest": result,
                            "layers_digest": layers
                        }
                        with open(self.processed_record_file, 'w', encoding='utf-8') as f:
                            json.dump(processed_records, f, indent=2, ensure_ascii=False)
                        success_models += 1
                        total_digests += 1 + len(layers)
                        msg = f"[完成] 模型：{model_name} 版本：{model_version}"
                        self.signals.progress.emit(msg)
                    else:
                        failed_models += 1
                        failed_list.append({"model": model_name, "version": model_version, "error": result})
                        msg = f"[错误] {result}"
                        self.signals.progress.emit(msg)
                except Exception as e:
                    failed_models += 1
                    failed_list.append({"model": model_name, "version": model_version, "error": str(e)})
                    msg = f"[线程错误] 模型：{model_name} 版本：{model_version} -> {e}"
                    self.signals.progress.emit(msg)
                finally:
                    finished_count += 1
                    self.signals.progress.emit(f"进度：{finished_count}/{total_models}")
        if failed_list:
            with open(self.error_log_file, 'w', encoding='utf-8') as f:
                json.dump(failed_list, f, indent=2, ensure_ascii=False)

        elapsed = time.time() - start_time
        msg = f"\n====== 多线程整理完成 ======\n总共模型版本数：{total_models}\n已跳过的模型数：{skipped_models}\n成功整理模型数：{success_models}\n失败模型数：{failed_models}\n总共复制 blob 文件数：{total_digests}"
        if failed_models > 0:
            msg += f"\n失败模型详情已写入：{self.error_log_file}"
        msg += f"\n总耗时：{elapsed:.2f} 秒"
        self.signals.progress.emit(msg)
        self.signals.finished.emit()

class DeleteFilesThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, tasks, model_base_dir):
        super().__init__()
        self.tasks = tasks
        self.model_base_dir = model_base_dir

    def run(self):
        total = len(self.tasks)
        done = 0
        for model_name, model_version in self.tasks:
            model_version_dir = os.path.join(self.model_base_dir, model_name, model_version)
            try:
                if os.path.isdir(model_version_dir):
                    shutil.rmtree(model_version_dir)
                    self.progress.emit(f"[删除] {model_name} - {model_version}")
                else:
                    self.progress.emit(f"[跳过] 文件不存在: {model_name} - {model_version}")
            except Exception as e:
                self.progress.emit(f"[错误] 删除失败: {model_name} - {model_version} -> {str(e)}")
            done += 1
            self.progress.emit(f"进度：{done}/{total}")
        self.finished.emit()

class MyListWidget(QListWidget):
    def mousePressEvent(self, event):
        item = self.itemAt(event.pos())
        if item is not None:
            rect = self.visualItemRect(item)
            check_rect = QRect(rect.left() + 4, rect.top() + (rect.height() - 16) // 2, 20, 20)
            if not check_rect.contains(event.pos()):
                if item.checkState() == Qt.Checked:
                    item.setCheckState(Qt.Unchecked)
                else:
                    item.setCheckState(Qt.Checked)
                return
        super().mousePressEvent(event)

class OllamaManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ollama 本地模型批量整理工具 v1.0")
        self.setGeometry(100, 100, 900, 700)
        self.font = QFont("微软雅黑", 14)
        self.config_file = CONFIG_FILE
        self.root_dir_Ollama = r"C:\Users\xxx\.ollama"
        self.root_dir_Ollama_new = r"L:\备份\Ollama备份\2025.08.01"
        self.load_config()  # 启动时优先覆盖默认值
        self.model_base_dir = os.path.join(self.root_dir_Ollama, r'models\manifests\registry.ollama.ai\library')
        self.model_name_list = os.listdir(self.model_base_dir) if os.path.exists(self.model_base_dir) else []
        self.processed_record_file = os.path.join(self.root_dir_Ollama_new, 'processed_models.json')
        self.error_log_file = os.path.join(self.root_dir_Ollama_new, 'error_log.json')
        self.init_ui()
        self.load_models()


    def init_ui(self):
        font = self.font
        main_widget = QWidget(self)
        self.setCentralWidget(main_widget)

        # 设置路径输入框
        self.dir_edit_1 = QLineEdit(f"{self.root_dir_Ollama}", self)
        self.dir_edit_1.setFont(font)
        self.dir_edit_2 = QLineEdit(f"{self.root_dir_Ollama_new}", self)
        self.dir_edit_2.setFont(font)
        self.dir_edit_1.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dir_edit_2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dir_edit_1.setMinimumWidth(400)
        self.dir_edit_2.setMinimumWidth(400)

        # 设置路径选择按钮
        self.select_dir_button_1 = QPushButton("选择Ollama根目录", self)
        self.select_dir_button_2 = QPushButton("选择整理后的目录", self)
        self.select_dir_button_1.setFixedWidth(180)
        self.select_dir_button_2.setFixedWidth(180)
        self.select_dir_button_1.setFont(font)
        self.select_dir_button_2.setFont(font)

        self.open_dir_button_1 = QPushButton("打开", self)
        self.open_dir_button_2 = QPushButton("打开", self)
        self.open_dir_button_1.setFont(font)
        self.open_dir_button_2.setFont(font)
        self.open_dir_button_1.setFixedWidth(100)
        self.open_dir_button_2.setFixedWidth(100)
        self.open_dir_button_1.clicked.connect(self.open_dir_1)
        self.open_dir_button_2.clicked.connect(self.open_dir_2)

        path1_layout = QHBoxLayout()
        path1_layout.addWidget(self.dir_edit_1)
        path1_layout.addWidget(self.select_dir_button_1)
        path1_layout.addWidget(self.open_dir_button_1)

        path2_layout = QHBoxLayout()
        path2_layout.addWidget(self.dir_edit_2)
        path2_layout.addWidget(self.select_dir_button_2)
        path2_layout.addWidget(self.open_dir_button_2)

        path_layout = QVBoxLayout()
        path_layout.addLayout(path1_layout)
        path_layout.addLayout(path2_layout)

        self.select_dir_button_1.clicked.connect(self.select_dir_1)
        self.select_dir_button_2.clicked.connect(self.select_dir_2)

        # 设置模型列表控件
        self.model_list_widget = MyListWidget(self)
        self.model_list_widget.setFont(font)
        self.model_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        self.model_list_widget.itemChanged.connect(self.on_model_item_changed)

        # 设置日志区
        self.text_log = QTextEdit(self)
        self.text_log.setReadOnly(True)
        self.text_log.setFont(font)
        self.text_log.setMinimumHeight(200)

        # 设置刷新按钮
        self.btn_refresh = QPushButton("刷新", self)
        self.btn_refresh.setStyleSheet("background-color: #2196F3; color: white;")
        self.btn_refresh.setFont(font)
        self.btn_refresh.clicked.connect(self.load_models)

        # 设置整理按钮
        self.btn_organize = QPushButton("整理", self)
        self.btn_organize.setStyleSheet("background-color: #00ff00; color: black;")
        self.btn_organize.setFont(font)
        self.btn_organize.clicked.connect(self.on_organize)

        # 设置删除按钮
        self.btn_delete = QPushButton("删除", self)
        self.btn_delete.setStyleSheet("background-color: #ff0000; color: white;")
        self.btn_delete.setFont(font)
        self.btn_delete.clicked.connect(self.on_delete)


        # 设置退出按钮
        self.btn_exit = QPushButton("退出", self)
        self.btn_exit.setStyleSheet("background-color: #000000; color: white;")
        self.btn_exit.setFont(font)
        self.btn_exit.clicked.connect(self.close)

        # 操作日志标签
        label = QLabel("操作日志/进度：")
        label.setFont(font)

        # 按钮布局
        btn_layout = QVBoxLayout()
        btn_layout.addWidget(self.btn_refresh)  # 按钮顺序：刷新
        btn_layout.addWidget(self.btn_organize)  # 然后是整理
        btn_layout.addWidget(self.btn_delete)  # 最后是删除
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_exit)  # 退出按钮

        # 中间布局，包含模型列表和按钮
        center_layout = QHBoxLayout()
        center_layout.addWidget(self.model_list_widget, stretch=2)
        center_layout.addLayout(btn_layout, stretch=1)

        # 主布局
        main_layout = QVBoxLayout()
        main_layout.addLayout(path_layout)
        main_layout.addLayout(center_layout)
        main_layout.addWidget(label)
        main_layout.addWidget(self.text_log)

        # 设置主窗口的布局
        main_widget.setLayout(main_layout)
        self.setFont(font)


    def open_dir_1(self):
        path = self.dir_edit_1.text().strip()
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "路径不存在", f"目录不存在：{path}")

    def open_dir_2(self):
        path = self.dir_edit_2.text().strip()
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "路径不存在", f"目录不存在：{path}")

    def select_dir_1(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择原始模型目录", self.root_dir_Ollama)
        if dir_path:
            self.root_dir_Ollama = dir_path
            self.dir_edit_1.setText(f"{self.root_dir_Ollama}")
            self.model_base_dir = os.path.join(self.root_dir_Ollama, r'models\manifests\registry.ollama.ai\library')
            self.model_name_list = os.listdir(self.model_base_dir) if os.path.exists(self.model_base_dir) else []
            self.save_config()
            self.load_models()

    def select_dir_2(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择整理输出目录", self.root_dir_Ollama_new)
        if dir_path:
            self.root_dir_Ollama_new = dir_path
            self.dir_edit_2.setText(f"{self.root_dir_Ollama_new}")
            self.save_config()

    def load_models(self):
        self.model_list_widget.blockSignals(True)
        self.model_list_widget.clear()
        self.model_name_list = os.listdir(self.model_base_dir) if os.path.exists(self.model_base_dir) else []
        for model_name in self.model_name_list:
            model_version_dir = os.path.join(self.model_base_dir, model_name)
            if not os.path.isdir(model_version_dir):
                continue
            for model_version in os.listdir(model_version_dir):
                item = QListWidgetItem(f"{model_name} - {model_version}")
                item.setCheckState(Qt.Unchecked)
                self.model_list_widget.addItem(item)
        self.model_list_widget.blockSignals(False)
        self.text_log.append("[刷新] 模型列表已更新，共 {} 个模型".format(self.model_list_widget.count()))

    def on_model_item_changed(self, item):
        pass

    def on_organize(self):
        selected_items = [item for item in self.model_list_widget.findItems("", Qt.MatchContains) if item.checkState() == Qt.Checked]
        if not selected_items:
            self.text_log.append("警告: 请先选择要整理的模型")
            return

        self.root_dir_Ollama = self.dir_edit_1.text().strip()
        self.root_dir_Ollama_new = self.dir_edit_2.text().strip()
        self.processed_record_file = os.path.join(self.root_dir_Ollama_new, 'processed_models.json')
        self.error_log_file = os.path.join(self.root_dir_Ollama_new, 'error_log.json')

        self.save_config()

        tasks = []
        for item in selected_items:
            model_name, model_version = item.text().split(" - ")
            tasks.append((model_name, model_version))

        self.text_log.clear()
        self.text_log.append("开始整理任务...\n")

        self.btn_organize.setEnabled(False)
        self.organize_thread = OrganizeThread(
            tasks, self.root_dir_Ollama, self.root_dir_Ollama_new,
            self.processed_record_file, self.error_log_file)
        self.organize_thread.signals.progress.connect(self.on_progress)
        self.organize_thread.signals.finished.connect(self.on_organize_finished)
        self.organize_thread.start()

    def on_progress(self, msg):
        self.text_log.append(msg)
        self.text_log.ensureCursorVisible()

    def on_organize_finished(self):
        self.btn_organize.setEnabled(True)
        self.text_log.append("\n整理任务已完成。")
        self.load_models()

    def on_delete(self):
        selected_items = [item for item in self.model_list_widget.findItems("", Qt.MatchContains) if item.checkState() == Qt.Checked]
        if not selected_items:
            self.text_log.append("警告: 请先选择要删除的模型")
            return
        reply = QMessageBox.question(self, "确认删除", "确定要删除选中模型吗？操作不可恢复！", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        tasks = []
        for item in selected_items:
            model_name, model_version = item.text().split(" - ")
            tasks.append((model_name, model_version))
        self.btn_delete.setEnabled(False)
        self.delete_thread = DeleteFilesThread(tasks, self.model_base_dir)
        self.delete_thread.progress.connect(self.on_progress)
        self.delete_thread.finished.connect(self.on_delete_finished)
        self.delete_thread.start()

    def on_delete_finished(self):
        self.btn_delete.setEnabled(True)
        self.text_log.append("\n删除任务已完成。")
        self.load_models()

    def save_config(self):
        config = {
            'root_dir_Ollama': self.dir_edit_1.text().strip(),
            'root_dir_Ollama_new': self.dir_edit_2.text().strip()
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.root_dir_Ollama = config.get('root_dir_Ollama', self.root_dir_Ollama)
                self.root_dir_Ollama_new = config.get('root_dir_Ollama_new', self.root_dir_Ollama_new)
            except Exception:
                pass

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = OllamaManager()
    window.show()
    sys.exit(app.exec_())
