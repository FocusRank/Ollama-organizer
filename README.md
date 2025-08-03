# Ollama Organizer - Local Model Management Tool

A graphical tool designed to manage local Ollama model files. It supports **batch organization**, **copy verification**, **version control**, and **safe deletion**—ideal for backing up, migrating, and archiving Ollama models.

![image-20250803173956409](C:\Users\xxx\PycharmProjects\Ollama-organizer\assets\image-20250803173956409.png)

---

## ✨ Features

- ✅ Select the **original Ollama model directory** and **output target directory**
- ✅ Automatically detects model names and versions
- ✅ Multi-threaded high-speed copying of `.blobs` and `manifests` files with verification
- ✅ Records processed models to avoid duplication
- ✅ Logs errors and failed models to a JSON file
- ✅ Full graphical interface (based on PyQt5)
- ✅ Supports **batch deletion** of selected models

---

## 📦 Dependencies

- Python >= 3.7
- PyQt5
- tqdm

Install dependencies via:

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install pyqt5 tqdm
```

---

## 🖥️ How to Use

### 1. Start the Application

```bash
python your_script_name.py
```

### 2. Basic Workflow

#### ✅ Organizing for the First Time:
1. Click **“Select Ollama Root”** to choose your `.ollama` directory (usually at `C:\Users\xxx\.ollama`)
2. Select an **output directory** (optional; default path can be changed)
3. Check the model versions you want to organize
4. Click the **“Organize”** button to start copying and verifying model data

#### 🗑️ Deleting Models:
- Select existing models and click **“Delete”** to permanently remove them from the source directory

---

## 🗃️ File Structure Overview

Organized models will be saved in the following structure:

```
<output_directory>/
├── <model_name>/
│   └── models/
│       ├── blobs/
│       │   ├── sha256-xxxxx
│       │   └── ...
│       └── manifests/registry.ollama.ai/library/<model_name>/<version>
├── processed_models.json     # Successfully processed models and their digests
├── error_log.json            # Information about failed models
```

---

## 📝 Configuration File

A `config.json` file is automatically generated after running the program:

```json
{
  "root_dir_Ollama": "C:/Users/xxx/.ollama",
  "root_dir_Ollama_new": "L:/Backup/Ollama_Backup/2025.08.01"
}
```

Used to remember your last-used input and output directories.

---

## 🧪 Screenshots (Optional)

It is recommended to upload screenshots to GitHub to help other users understand the layout and workflow, such as:

- Main interface: directory fields + model list + buttons
- In-progress log area during organization
- Completion or deletion confirmations

---

## 🚧 Notes

- This tool only supports Ollama’s local model structure (`.ollama/models/...`)
- Ensure enough disk space is available, especially for large `.blobs` files
- If any model files are missing, they will be logged and skipped automatically

---

## 📜 License

MIT License

---

## 👤 Author

Developed and maintained by [FocusRank](https://github.com/FocusRank).  
Feel free to open an issue or submit a pull request.
