# 本地开发环境搭建指南

本项目基于 Python 和 FastAPI，使用 `uvicorn` 作为开发服务器。以下为完整的启动步骤。

---

## 创建虚拟环境

建议使用虚拟环境隔离依赖，防止全局污染：

```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
# 或在 Windows 上:
# venv\Scripts\activate
```

---

## 安装依赖

在虚拟环境中安装项目依赖：

```bash
pip install -r requirements.txt
```

---

## 启动服务

使用 `uvicorn` 启动 FastAPI 服务：

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

启动后访问地址：

```
http://localhost:8000
```

---

## 安装 FFmpeg（用于音视频处理）

部分功能依赖 FFmpeg，请确保本地已安装。
项目内附带了一键安装脚本，可用于自动安装 FFmpeg：

### 安装方式：

```bash
# 安装 FFmpeg
bash install_ffmpeg.sh

# 验证安装
ffmpeg -version
```


---

## 常见目录说明

| 目录 / 文件         | 说明                   |
|---------------------|------------------------|
| `app.py`            | FastAPI 主程序入口     |
| `data/`             | 视频/图像临时数据目录  |
| `requirements.txt`  | 依赖列表               |
| `install_ffmpeg.sh` | 一键安装 FFmpeg 脚本   |

---


