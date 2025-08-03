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

def copy_model_files_and_verify(model_name, model_version, target_dir, source_dir, blob_cache_dir):
    try:
        source_models_dir = os.path.join(source_dir, 'models')
        manifests_dir = os.path.join(source_models_dir, f'manifests/registry.ollama.ai/library/{model_name}')
        relative_model_dir = f'manifests/registry.ollama.ai/library/{model_name}'
        new_models_dir = os.path.join(target_dir, model_version, 'models')
        new_blobs_dir = os.path.join(new_models_dir, 'blobs')
        new_model_dir = os.path.join(new_models_dir, relative_model_dir)
        model_config_path = os.path.join(manifests_dir, model_version)
        new_model_config_path = os.path.join(new_model_dir, model_version)
        make_dir(new_model_dir)
        make_dir(new_blobs_dir)
        shutil.copy(model_config_path, new_model_config_path)
        with open(model_config_path, 'r', encoding='utf-8') as f:
            content = json.load(f)
        config_digest = content['config']['digest'].replace('sha256:', 'sha256-')
        digest_src = os.path.join(blob_cache_dir, config_digest)
        digest_dst = os.path.join(new_blobs_dir, config_digest)
        shutil.copy(digest_src, digest_dst)
        if not os.path.exists(digest_dst):
            raise RuntimeError(f"Missing config digest file: {digest_dst}")
        layer_digests = []
        for layer in content['layers']:
            digest = layer['digest'].replace('sha256:', 'sha256-')
            src = os.path.join(blob_cache_dir, digest)
            dst = os.path.join(new_blobs_dir, digest)
            shutil.copy(src, dst)
            if not os.path.exists(dst):
                raise RuntimeError(f"Missing layer digest file: {dst}")
            layer_digests.append(layer['digest'])
        return True, config_digest, layer_digests
    except Exception as e:
        return False, f"{model_name}/{model_version} -> {e}", None

class WorkerSignals(QObject):
    progress = pyqtSignal(str)
    result = pyqtSignal(dict)
    finished = pyqtSignal()

class OrganizeThread(QThread):
    def __init__(self, tasks, source_dir, target_dir, record_file, error_log_file):
        super().__init__()
        self.tasks = tasks
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.record_file = record_file
        self.error_log_file = error_log_file
        self.signals = WorkerSignals()

    def run(self):
        processed_records = {}
        if os.path.exists(self.record_file):
            with open(self.record_file, 'r', encoding='utf-8') as f:
                processed_records = json.load(f)
        blob_cache_dir = os.path.join(self.source_dir, 'models', 'blobs')

        success_count = 0
        failure_count = 0
        total_digests = 0
        failed_list = []
        skipped = 0
        total_tasks = len(self.tasks)

        start_time = time.time()
        self.signals.progress.emit(f"Total model versions to process: {total_tasks}\n")

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            futures = {}
            for model_name, model_version in self.tasks:
                if model_name in processed_records and model_version in processed_records[model_name]:
                    skipped += 1
                    self.signals.progress.emit(f"[Skipped] Model: {model_name}, Version: {model_version}")
                    continue
                processed_records.setdefault(model_name, {})
                new_model_dir = os.path.join(self.target_dir, model_name)
                future = executor.submit(copy_model_files_and_verify, model_name, model_version, new_model_dir, self.source_dir, blob_cache_dir)
                futures[future] = (model_name, model_version)

            finished = skipped
            for future in as_completed(futures):
                model_name, model_version = futures[future]
                try:
                    success, result, layers = future.result()
                    if success:
                        processed_records[model_name][model_version] = {
                            "config_digest": result,
                            "layers_digest": layers
                        }
                        with open(self.record_file, 'w', encoding='utf-8') as f:
                            json.dump(processed_records, f, indent=2, ensure_ascii=False)
                        success_count += 1
                        total_digests += 1 + len(layers)
                        self.signals.progress.emit(f"[Done] Model: {model_name}, Version: {model_version}")
                    else:
                        failure_count += 1
                        failed_list.append({"model": model_name, "version": model_version, "error": result})
                        self.signals.progress.emit(f"[Error] {result}")
                except Exception as e:
                    failure_count += 1
                    failed_list.append({"model": model_name, "version": model_version, "error": str(e)})
                    self.signals.progress.emit(f"[Thread Error] {model_name}/{model_version} -> {e}")
                finally:
                    finished += 1
                    self.signals.progress.emit(f"Progress: {finished}/{total_tasks}")

        if failed_list:
            with open(self.error_log_file, 'w', encoding='utf-8') as f:
                json.dump(failed_list, f, indent=2, ensure_ascii=False)

        elapsed = time.time() - start_time
        msg = (
            f"\n====== Organizing Completed ======\n"
            f"Total model versions: {total_tasks}\n"
            f"Skipped: {skipped}\n"
            f"Success: {success_count}\n"
            f"Failed: {failure_count}\n"
            f"Total blob files copied: {total_digests}"
        )
        if failure_count > 0:
            msg += f"\nFailed details written to: {self.error_log_file}"
        msg += f"\nElapsed time: {elapsed:.2f} seconds"
        self.signals.progress.emit(msg)
        self.signals.finished.emit()

class DeleteFilesThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, tasks, base_dir):
        super().__init__()
        self.tasks = tasks
        self.base_dir = base_dir

    def run(self):
        total = len(self.tasks)
        done = 0
        for model_name, model_version in self.tasks:
            version_dir = os.path.join(self.base_dir, model_name, model_version)
            try:
                if os.path.isdir(version_dir):
                    shutil.rmtree(version_dir)
                    self.progress.emit(f"[Deleted] {model_name} - {model_version}")
                else:
                    self.progress.emit(f"[Skipped] Not found: {model_name} - {model_version}")
            except Exception as e:
                self.progress.emit(f"[Error] Delete failed: {model_name} - {model_version} -> {str(e)}")
            done += 1
            self.progress.emit(f"Progress: {done}/{total}")
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
        self.setWindowTitle("Ollama Local Model Organizer v1.0")
        self.setGeometry(100, 100, 900, 700)
        self.font = QFont("Arial", 14)
        self.config_file = CONFIG_FILE
        self.root_dir_Ollama = r"C:\Users\xxx\.ollama"
        self.root_dir_Ollama_new = r"L:\Backup\Ollama_Backup\2025.08.01"
        self.load_config()
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

        self.dir_edit_1 = QLineEdit(self.root_dir_Ollama, self)
        self.dir_edit_2 = QLineEdit(self.root_dir_Ollama_new, self)
        for edit in [self.dir_edit_1, self.dir_edit_2]:
            edit.setFont(font)
            edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            edit.setMinimumWidth(400)

        self.select_dir_button_1 = QPushButton("Select Ollama Root", self)
        self.select_dir_button_2 = QPushButton("Select Output Directory", self)
        self.open_dir_button_1 = QPushButton("Open", self)
        self.open_dir_button_2 = QPushButton("Open", self)

        for btn in [self.select_dir_button_1, self.select_dir_button_2, self.open_dir_button_1, self.open_dir_button_2]:
            btn.setFont(font)
        self.select_dir_button_1.setFixedWidth(180)
        self.select_dir_button_2.setFixedWidth(180)
        self.open_dir_button_1.setFixedWidth(100)
        self.open_dir_button_2.setFixedWidth(100)

        self.open_dir_button_1.clicked.connect(self.open_dir_1)
        self.open_dir_button_2.clicked.connect(self.open_dir_2)
        self.select_dir_button_1.clicked.connect(self.select_dir_1)
        self.select_dir_button_2.clicked.connect(self.select_dir_2)

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

        self.model_list_widget = MyListWidget(self)
        self.model_list_widget.setFont(font)
        self.model_list_widget.setSelectionMode(QAbstractItemView.MultiSelection)
        self.model_list_widget.itemChanged.connect(self.on_model_item_changed)

        self.text_log = QTextEdit(self)
        self.text_log.setReadOnly(True)
        self.text_log.setFont(font)
        self.text_log.setMinimumHeight(200)

        self.btn_refresh = QPushButton("Refresh", self)
        self.btn_organize = QPushButton("Organize", self)
        self.btn_delete = QPushButton("Delete", self)
        self.btn_exit = QPushButton("Exit", self)

        self.btn_refresh.setStyleSheet("background-color: #2196F3; color: white;")
        self.btn_organize.setStyleSheet("background-color: #00FF00; color: black;")
        self.btn_delete.setStyleSheet("background-color: #FF0000; color: white;")
        self.btn_exit.setStyleSheet("background-color: #000000; color: white;")

        for btn in [self.btn_refresh, self.btn_organize, self.btn_delete, self.btn_exit]:
            btn.setFont(font)

        self.btn_refresh.clicked.connect(self.load_models)
        self.btn_organize.clicked.connect(self.on_organize)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_exit.clicked.connect(self.close)

        label = QLabel("Log / Progress:")
        label.setFont(font)

        btn_layout = QVBoxLayout()
        for btn in [self.btn_refresh, self.btn_organize, self.btn_delete]:
            btn_layout.addWidget(btn)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_exit)

        center_layout = QHBoxLayout()
        center_layout.addWidget(self.model_list_widget, stretch=2)
        center_layout.addLayout(btn_layout, stretch=1)

        main_layout = QVBoxLayout()
        main_layout.addLayout(path_layout)
        main_layout.addLayout(center_layout)
        main_layout.addWidget(label)
        main_layout.addWidget(self.text_log)

        main_widget.setLayout(main_layout)
        self.setFont(font)

    def open_dir_1(self):
        path = self.dir_edit_1.text().strip()
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Path Not Found", f"Directory does not exist: {path}")

    def open_dir_2(self):
        path = self.dir_edit_2.text().strip()
        if os.path.exists(path):
            os.startfile(path)
        else:
            QMessageBox.warning(self, "Path Not Found", f"Directory does not exist: {path}")

    def select_dir_1(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Ollama Root", self.root_dir_Ollama)
        if dir_path:
            self.root_dir_Ollama = dir_path
            self.dir_edit_1.setText(self.root_dir_Ollama)
            self.model_base_dir = os.path.join(self.root_dir_Ollama, r'models\manifests\registry.ollama.ai\library')
            self.model_name_list = os.listdir(self.model_base_dir) if os.path.exists(self.model_base_dir) else []
            self.save_config()
            self.load_models()

    def select_dir_2(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.root_dir_Ollama_new)
        if dir_path:
            self.root_dir_Ollama_new = dir_path
            self.dir_edit_2.setText(self.root_dir_Ollama_new)
            self.save_config()

    def load_models(self):
        self.model_list_widget.blockSignals(True)
        self.model_list_widget.clear()
        self.model_name_list = os.listdir(self.model_base_dir) if os.path.exists(self.model_base_dir) else []
        for model_name in self.model_name_list:
            version_dir = os.path.join(self.model_base_dir, model_name)
            if not os.path.isdir(version_dir):
                continue
            for model_version in os.listdir(version_dir):
                item = QListWidgetItem(f"{model_name} - {model_version}")
                item.setCheckState(Qt.Unchecked)
                self.model_list_widget.addItem(item)
        self.model_list_widget.blockSignals(False)
        self.text_log.append(f"[Refreshed] {self.model_list_widget.count()} models loaded.")

    def on_model_item_changed(self, item):
        pass

    def on_organize(self):
        selected_items = [item for item in self.model_list_widget.findItems("", Qt.MatchContains) if item.checkState() == Qt.Checked]
        if not selected_items:
            self.text_log.append("Warning: Please select models to organize.")
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
        self.text_log.append("Organizing selected models...\n")
        self.btn_organize.setEnabled(False)

        self.organize_thread = OrganizeThread(tasks, self.root_dir_Ollama, self.root_dir_Ollama_new, self.processed_record_file, self.error_log_file)
        self.organize_thread.signals.progress.connect(self.on_progress)
        self.organize_thread.signals.finished.connect(self.on_organize_finished)
        self.organize_thread.start()

    def on_progress(self, msg):
        self.text_log.append(msg)
        self.text_log.ensureCursorVisible()

    def on_organize_finished(self):
        self.btn_organize.setEnabled(True)
        self.text_log.append("\nOrganizing complete.")
        self.load_models()

    def on_delete(self):
        selected_items = [item for item in self.model_list_widget.findItems("", Qt.MatchContains) if item.checkState() == Qt.Checked]
        if not selected_items:
            self.text_log.append("Warning: Please select models to delete.")
            return
        reply = QMessageBox.question(self, "Confirm Delete", "Are you sure to delete selected models? This cannot be undone.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
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
        self.text_log.append("\nDeletion complete.")
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

