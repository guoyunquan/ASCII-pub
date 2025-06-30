#!/bin/bash

# FFmpeg 自动安装脚本
# 支持 Ubuntu/Debian, CentOS/RHEL, macOS

echo "🎬 开始安装 FFmpeg..."

# 检测操作系统
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    if command -v apt-get >/dev/null 2>&1; then
        # Ubuntu/Debian
        echo "📦 检测到 Ubuntu/Debian 系统"
        sudo apt-get update
        sudo apt-get install -y ffmpeg
    elif command -v yum >/dev/null 2>&1; then
        # CentOS/RHEL
        echo "📦 检测到 CentOS/RHEL 系统"
        sudo yum install -y epel-release
        sudo yum install -y ffmpeg ffmpeg-devel
    elif command -v dnf >/dev/null 2>&1; then
        # Fedora
        echo "📦 检测到 Fedora 系统"
        sudo dnf install -y ffmpeg ffmpeg-devel
    else
        echo "❌ 不支持的 Linux 发行版"
        exit 1
    fi
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "📦 检测到 macOS 系统"
    if command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    else
        echo "❌ 请先安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        exit 1
    fi
else
    echo "❌ 不支持的操作系统: $OSTYPE"
    exit 1
fi

# 验证安装
echo "🔍 验证 FFmpeg 安装..."
if command -v ffmpeg >/dev/null 2>&1; then
    echo "✅ FFmpeg 安装成功！"
    ffmpeg -version | head -1
    echo ""
    echo "🔍 验证 FFprobe 安装..."
    if command -v ffprobe >/dev/null 2>&1; then
        echo "✅ FFprobe 安装成功！"
        ffprobe -version | head -1
    else
        echo "⚠️ FFprobe 未找到，某些功能可能不可用"
    fi
else
    echo "❌ FFmpeg 安装失败"
    exit 1
fi

echo ""
echo "🎉 音频处理环境准备完成！"
echo "📝 你现在可以启动视频转换服务，生成的 ASCII 视频将包含原始音频。" 