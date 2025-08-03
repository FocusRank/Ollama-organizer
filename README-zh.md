# Ollama Organizer 本地模型整理工具

一个用于整理 Ollama 本地模型文件的图形界面工具，可对模型进行 **批量整理**、**复制验证**、**版本管理** 和 **清理删除** 操作，适用于模型文件的备份迁移和版本归档。

![image-20250803173711700](C:\Users\xxx\PycharmProjects\Ollama-organizer\assets\image-20250803173711700.png)



---

## ✨ 功能特点

- ✅ 支持 **选择原始 Ollama 模型目录** 和 **输出整理目录**
- ✅ 自动识别模型名称与版本
- ✅ 多线程高效复制 `.blobs` 和 `manifests` 文件，校验完整性
- ✅ 可记录已处理模型，避免重复整理
- ✅ 支持错误日志输出与失败记录
- ✅ 提供图形界面操作（基于 PyQt5）
- ✅ 支持选中模型的 **批量删除**

---

## 📦 环境依赖

- Python >= 3.7
- PyQt5
- tqdm

安装依赖：

```bash
pip install -r requirements.txt
```

或手动安装：

```bash
pip install pyqt5 tqdm
```

---

## 🖥️ 使用方法

### 1. 启动程序

```bash
python your_script_name.py
```

### 2. 操作流程

#### ✅ 初次整理：
1. 点击“选择 Ollama 根目录”按钮，定位你的 `.ollama` 主目录（通常位于 `C:\Users\xxx\.ollama`）
2. 选择“整理输出目录”（可选，默认路径可修改）
3. 勾选要整理的模型版本
4. 点击“整理”按钮，程序将自动复制并校验模型数据文件

#### 🗑️ 删除模型：
- 勾选已存在的模型版本，点击“删除”按钮，即可从原始目录中删除该模型。

---

## 🗃️ 文件结构说明

程序会将整理后的模型复制至如下结构：

```
<整理输出目录>/
├── <模型名>/
│   └── models/
│       ├── blobs/
│       │   ├── sha256-xxxxx
│       │   └── ...
│       └── manifests/registry.ollama.ai/library/<模型名>/<版本号>
├── processed_models.json     # 记录已成功处理的模型及其 digest 信息
├── error_log.json            # 记录处理失败的模型信息
```

---

## 📝 配置文件

程序运行后自动生成 `config.json`：

```json
{
  "root_dir_Ollama": "C:/Users/xxx/.ollama",
  "root_dir_Ollama_new": "L:/备份/Ollama备份/2025.08.01"
}
```

用于记忆上次打开的输入输出目录。

---

## 🧪 测试截图建议（可选）

建议在 GitHub 上传实际运行界面的截图，帮助其他用户理解 UI 布局和功能，例如：

- 主界面：路径设置 + 模型列表 + 按钮区
- 整理任务进行中：日志输出区域
- 整理完成或删除成功后的提示

---

## 🚧 注意事项

- 本工具仅支持 Ollama 的本地模型结构（`.ollama/models/...`）
- 请确保目标磁盘有足够空间，特别是 `.blobs` 文件体积较大
- 遇到模型丢失或文件缺失将记录错误日志并跳过

---

## 📜 License

MIT License

---

## 👤 作者信息

由 [FocusRank](https://github.com/FocusRank) 开发与维护。如有问题欢迎提交 issue 或 pull request。
