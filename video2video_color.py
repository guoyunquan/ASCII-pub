import cv2
import numpy as np
from PIL import Image, ImageFont, ImageDraw, ImageOps
from fastapi import File, UploadFile, APIRouter, Form, WebSocket, WebSocketDisconnect
import os
import uuid
import time
import asyncio
from fastapi.responses import JSONResponse
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing
from functools import partial
import json
from typing import Dict
import subprocess
import shutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import glob

# 假设其他导入和函数保持不变
video = APIRouter()

# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        self.active_connections[task_id] = websocket

    def disconnect(self, task_id: str):
        if task_id in self.active_connections:
            del self.active_connections[task_id]

    async def send_progress(self, task_id: str, progress: float, message: str = ""):
        if task_id in self.active_connections:
            try:
                await self.active_connections[task_id].send_text(json.dumps({
                    "type": "progress",
                    "progress": progress,
                    "message": message
                }))
            except:
                # 连接已断开，移除
                self.disconnect(task_id)

    async def send_completed(self, task_id: str, video_url: str):
        if task_id in self.active_connections:
            try:
                await self.active_connections[task_id].send_text(json.dumps({
                    "type": "completed",
                    "video_url": video_url
                }))
            except:
                self.disconnect(task_id)

    async def send_error(self, task_id: str, error_message: str):
        if task_id in self.active_connections:
            try:
                await self.active_connections[task_id].send_text(json.dumps({
                    "type": "error",
                    "message": error_message
                }))
            except:
                self.disconnect(task_id)

    async def send_error(self, task_id: str, error_message: str):
        if task_id in self.active_connections:
            try:
                await self.active_connections[task_id].send_text(json.dumps({
                    "type": "error",
                    "message": error_message
                }))
            except:
                self.disconnect(task_id)

manager = ConnectionManager()

# 任务状态管理
task_status: Dict[str, dict] = {}

# 定时清理调度器
scheduler = AsyncIOScheduler()

async def cleanup_old_videos():
    """
    清理超过24小时的媒体文件（视频和图片）
    """
    try:
        data_dir = "data/"
        if not os.path.exists(data_dir):
            print("data目录不存在，跳过清理")
            return
        
        # 计算24小时前的时间戳
        cutoff_time = datetime.now() - timedelta(hours=24)
        cutoff_timestamp = cutoff_time.timestamp()
        
        # 查找所有媒体文件（视频和图片）
        media_patterns = [
            os.path.join(data_dir, "*.mp4"),
            os.path.join(data_dir, "*.avi"),
            os.path.join(data_dir, "*.mov"),
            os.path.join(data_dir, "*_with_audio.mp4"),
            os.path.join(data_dir, "*_input.mp4"),
            os.path.join(data_dir, "*.jpg"),
            os.path.join(data_dir, "*.jpeg"),
            os.path.join(data_dir, "*.png"),
            os.path.join(data_dir, "*_input.jpg"),
            os.path.join(data_dir, "*_input.jpeg"),
            os.path.join(data_dir, "*_input.png")
        ]
        
        deleted_count = 0
        total_size_freed = 0
        
        for pattern in media_patterns:
            for file_path in glob.glob(pattern):
                try:
                    # 获取文件修改时间
                    file_mtime = os.path.getmtime(file_path)
                    
                    # 如果文件超过24小时
                    if file_mtime < cutoff_timestamp:
                        # 获取文件大小
                        file_size = os.path.getsize(file_path)
                        
                        # 删除文件
                        os.remove(file_path)
                        
                        deleted_count += 1
                        total_size_freed += file_size
                        
                        print(f"已删除过期文件: {os.path.basename(file_path)} ({file_size/1024/1024:.1f}MB)")
                        
                except Exception as e:
                    print(f"删除文件失败 {file_path}: {str(e)}")
        
        if deleted_count > 0:
            print(f"清理完成! 删除了 {deleted_count} 个文件，释放空间 {total_size_freed/1024/1024:.1f}MB")
        else:
            print("定时清理检查完成，没有发现需要清理的过期文件")
            
    except Exception as e:
        print(f"定时清理异常: {str(e)}")

def start_cleanup_scheduler():
    """
    启动定时清理调度器
    """
    try:
        # 添加定时任务：每天凌晨2点执行清理
        scheduler.add_job(
            cleanup_old_videos,
            'cron',
            hour=2,
            minute=0,
            id='daily_cleanup',
            replace_existing=True
        )
        
        # 也可以添加一个启动时立即执行一次的任务
        scheduler.add_job(
            cleanup_old_videos,
            'date',
            run_date=datetime.now() + timedelta(seconds=30),  # 启动30秒后执行一次
            id='startup_cleanup',
            replace_existing=True
        )
        
        scheduler.start()
        print("定时清理调度器已启动 - 每天凌晨2点自动清理超过24小时的媒体文件")
        print("启动清理任务将在30秒后执行一次")
        
    except Exception as e:
        print(f"启动定时清理调度器失败: {str(e)}")

def stop_cleanup_scheduler():
    """
    停止定时清理调度器
    """
    try:
        if scheduler.running:
            scheduler.shutdown()
            print("定时清理调度器已停止")
    except Exception as e:
        print(f"停止定时清理调度器失败: {str(e)}")

# 音频合并函数
async def merge_audio_with_video(original_video_path: str, ascii_video_path: str, output_path: str, task_id: str = None) -> bool:
    """
    使用 ffmpeg 将原始视频的音频与生成的 ASCII 视频合并
    
    Args:
        original_video_path: 原始视频文件路径
        ascii_video_path: 生成的ASCII视频文件路径  
        output_path: 输出文件路径
    
    Returns:
        bool: 是否成功合并
    """
    try:
        # 发送进度：检查工具
        if task_id:
            await manager.send_progress(task_id, 85, "检查音频处理工具...")
        
        # 检查 ffmpeg 是否可用
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print("ffmpeg 不可用，跳过音频合并")
            if task_id:
                await manager.send_progress(task_id, 90, "音频工具不可用，跳过音频处理")
            return False
        
        # 发送进度：分析音频轨道
        if task_id:
            await manager.send_progress(task_id, 87, "分析原视频音频轨道...")
        
        print(f"开始合并音频...")
        print(f"   原始视频: {original_video_path}")
        print(f"   ASCII视频: {ascii_video_path}")
        print(f"   输出路径: {output_path}")
        
        # 临时输出文件
        temp_output = f"{output_path}_temp.mp4"
        
        # 发送进度：匹配音频轨道
        if task_id:
            await manager.send_progress(task_id, 89, "匹配音频轨道与视频流...")
        
        # ffmpeg 命令：将 ASCII 视频与原始视频的音频合并
        # -i 输入1: ASCII视频 (视频流)
        # -i 输入2: 原始视频 (音频流)
        # -c:v copy: 复制视频流（不重新编码）
        # -c:a aac: 音频编码为aac
        # -map 0:v: 使用第一个输入的视频流
        # -map 1:a: 使用第二个输入的音频流
        # -shortest: 以最短流为准
        cmd = [
            'ffmpeg',
            '-i', ascii_video_path,    # ASCII 视频（视频流）
            '-i', original_video_path,  # 原始视频（音频流）
            '-c:v', 'copy',            # 复制视频流
            '-c:a', 'aac',             # 音频编码
            '-map', '0:v',             # 使用第一个输入的视频
            '-map', '1:a?',            # 使用第二个输入的音频（如果存在）
            '-shortest',               # 以最短流为准
            '-y',                      # 覆盖输出文件
            temp_output
        ]
        
        # 发送进度：开始音频合并
        if task_id:
            await manager.send_progress(task_id, 91, "正在合并音频与视频...")
        
        # 执行 ffmpeg 命令
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            # 发送进度：验证合并结果
            if task_id:
                await manager.send_progress(task_id, 94, "验证音频合并结果...")
            
            # 成功，替换原文件
            if os.path.exists(temp_output):
                shutil.move(temp_output, output_path)
                print(f"音频合并成功！")
                
                # 发送进度：音频合并完成
                if task_id:
                    await manager.send_progress(task_id, 96, "音频合并完成！")
                    
                return True
            else:
                print(f"临时文件不存在: {temp_output}")
                if task_id:
                    await manager.send_progress(task_id, 90, "音频合并异常：临时文件丢失")
                return False
        else:
            print(f"ffmpeg 执行失败:")
            print(f"   stdout: {result.stdout}")
            print(f"   stderr: {result.stderr}")
            
            # 发送进度：音频合并失败
            if task_id:
                await manager.send_progress(task_id, 90, "音频合并失败，保留无音频版本")
            
            # 清理临时文件
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False
        
    except subprocess.TimeoutExpired:
        print("ffmpeg 执行超时")
        if task_id:
            await manager.send_progress(task_id, 90, "音频处理超时，保留无音频版本")
        return False
    except Exception as e:
        print(f"音频合并异常: {str(e)}")
        if task_id:
            await manager.send_progress(task_id, 90, f"音频处理异常: {str(e)}")
        return False

async def check_video_has_audio(video_path: str, task_id: str = None) -> bool:
    """
    检查视频文件是否包含音频流
    
    Args:
        video_path: 视频文件路径
    
    Returns:
        bool: 是否包含音频
    """
    try:
        # 发送进度：检测音频流
        if task_id:
            await manager.send_progress(task_id, 84, "检测视频中的音频流...")
        
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-select_streams', 'a',
            '-show_entries', 'stream=codec_type',
            '-of', 'csv=p=0',
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        has_audio = result.returncode == 0 and 'audio' in result.stdout
        
        # 发送检测结果
        if task_id:
            if has_audio:
                await manager.send_progress(task_id, 85, "发现音频轨道，准备合并...")
            else:
                await manager.send_progress(task_id, 90, "未发现音频轨道，跳过音频处理")
        
        return has_audio
        
    except Exception as e:
        print(f"⚠️ 检查音频流失败: {str(e)}")
        if task_id:
            await manager.send_progress(task_id, 90, f"音频检测失败: {str(e)}")
        return False

# 异步音频处理函数
async def process_audio_async(original_video_path: str, ascii_video_path: str, task_id: str) -> str:
    """
    异步处理音频合并
    
    Args:
        original_video_path: 原始视频文件路径
        ascii_video_path: ASCII视频文件路径
        task_id: 任务ID
    
    Returns:
        str: 最终输出文件路径
    """
    try:
        # 检查原视频是否有音频
        if await check_video_has_audio(original_video_path, task_id):
            print(f"原视频包含音频，开始合并...")
            
            # 创建带音频的最终输出文件
            final_output = f"data/{str(uuid.uuid4())}_with_audio.mp4"
            
            # 合并音频
            if await merge_audio_with_video(original_video_path, ascii_video_path, final_output, task_id):
                # 成功合并，删除无音频版本
                if os.path.exists(ascii_video_path):
                    os.remove(ascii_video_path)
                
                print(f"音频合并成功！最终文件: {final_output}")
                return final_output
            else:
                print(f"音频合并失败，保留无音频版本")
                return ascii_video_path
        else:
            print(f"原视频不包含音频流，跳过音频处理")
            return ascii_video_path
            
    except Exception as e:
        print(f"音频处理异常: {str(e)}")
        await manager.send_progress(task_id, 90, f"音频处理异常: {str(e)}")
        return ascii_video_path


class Args:
    def __init__(self, input_file_path: str, mode: str, background: str, num_cols: int, scale: int, fps: int,
                 overlay_ratio: float, keep_aspect_ratio: bool = True, target_width: int = None, target_height: int = None):
        self.input = input_file_path
        self.output = f"data/{str(uuid.uuid4())}.mp4"
        self.mode = mode
        self.background = background
        self.num_cols = num_cols
        self.scale = scale
        self.fps = fps
        self.overlay_ratio = overlay_ratio
        self.keep_aspect_ratio = keep_aspect_ratio
        self.target_width = target_width
        self.target_height = target_height


def get_args(input_file_path: str, mode: str = "complex", background: str = "black",
             num_cols: int = 100, scale: int = 1, fps: int = 30, overlay_ratio: float = 0.2,
             keep_aspect_ratio: bool = True, target_width: int = None, target_height: int = None):
    return Args(input_file_path, mode, background, num_cols, scale, fps, overlay_ratio, 
                keep_aspect_ratio, target_width, target_height)





def process_frame_ultra_fast(frame, char_list, num_chars, num_cols, num_rows, cell_width, cell_height, 
                            final_width, final_height, bg_code):
    """
    超音速帧处理 - 完全跳过字符渲染，直接用颜色块模拟
    """
    height, width = frame.shape[:2]
    
    # 直接创建输出数组
    out_image = np.full((final_height, final_width, 3), bg_code, dtype=np.uint8)
    
    # 计算每个区域的尺寸
    cell_h = final_height // num_rows
    cell_w = final_width // num_cols
    
    # 批量处理 - 矢量化操作
    for i in range(num_rows):
        for j in range(num_cols):
            # 原始帧区域
            y1, y2 = int(i * cell_height), min(int((i + 1) * cell_height), height)
            x1, x2 = int(j * cell_width), min(int((j + 1) * cell_width), width)
            
            # 输出位置
            out_y1, out_y2 = i * cell_h, min((i + 1) * cell_h, final_height)
            out_x1, out_x2 = j * cell_w, min((j + 1) * cell_w, final_width)
            
            if y2 > y1 and x2 > x1 and out_y2 > out_y1 and out_x2 > out_x1:
                # 超快速计算
                cell = frame[y1:y2, x1:x2]
                if cell.size > 0:
                    # 一次性计算所有需要的值
                    avg_color = np.mean(cell, axis=(0, 1)).astype(np.uint8)
                    brightness = np.mean(cell)
                    
                    # 根据亮度调整颜色强度（模拟字符密度）
                    char_idx = min(int(brightness * num_chars / 255), num_chars - 1)
                    intensity = char_idx / num_chars
                    
                    # 创建带有字符特征的颜色
                    # 亮度高的地方用亮色，暗的地方用暗色
                    if intensity > 0.7:  # 亮字符区域
                        final_color = (avg_color * 0.9).astype(np.uint8)
                    elif intensity > 0.4:  # 中等字符区域
                        final_color = (avg_color * 0.6).astype(np.uint8)
                    else:  # 暗字符区域
                        final_color = (avg_color * 0.3).astype(np.uint8)
                    
                    # 直接填充区域
                    out_image[out_y1:out_y2, out_x1:out_x2] = final_color
    
    return out_image


def create_char_cache(char_list, font, char_width, char_height, bg_code):
    """
    预渲染字符缓存 - 一次性渲染所有字符，后续直接拷贝
    """
    print(f"🔥 创建字符缓存: {len(char_list)}个字符...")
    
    char_cache = {}
    
    for char in char_list:
        # 创建字符模板（白色字符，透明背景）
        char_img = Image.new("RGBA", (char_width, char_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(char_img)
        draw.text((0, 0), char, fill=(255, 255, 255, 255), font=font)
        
        # 转换为numpy数组并提取alpha通道
        char_array = np.array(char_img)
        alpha_mask = char_array[:, :, 3] / 255.0  # 归一化alpha通道
        
        # 存储alpha掩码（用于后续颜色混合）
        char_cache[char] = alpha_mask
    
    print(f"✅ 字符缓存创建完成!")
    return char_cache


def process_frame_cached_chars(frame, char_list, num_chars, num_cols, num_rows, cell_width, cell_height, 
                              final_width, final_height, bg_code, char_cache, char_width, char_height):
    """
    缓存字符渲染 - 使用预渲染缓存，超快速度
    """
    height, width = frame.shape[:2]
    
    # 创建输出图像
    out_image = np.full((final_height, final_width, 3), bg_code, dtype=np.uint8)
    
    # 计算字符在画布上的间距
    char_spacing_w = final_width / num_cols
    char_spacing_h = final_height / num_rows
    
    for i in range(num_rows):
        for j in range(num_cols):
            # 原始帧区域
            y1, y2 = int(i * cell_height), min(int((i + 1) * cell_height), height)
            x1, x2 = int(j * cell_width), min(int((j + 1) * cell_width), width)
            
            if y2 > y1 and x2 > x1:
                # 快速提取单元格
                cell = frame[y1:y2, x1:x2]
                if cell.size > 0:
                    # numpy快速计算
                    avg_color = np.mean(cell, axis=(0, 1)).astype(np.uint8)
                    brightness = np.mean(cell)
                    
                    # 选择字符
                    char_idx = min(int(brightness * num_chars / 255), num_chars - 1)
                    char = char_list[char_idx]
                    
                    # 计算字符位置
                    char_x = int(j * char_spacing_w + (char_spacing_w - char_width) / 2)
                    char_y = int(i * char_spacing_h + (char_spacing_h - char_height) / 2)
                    
                    # 确保不越界
                    end_x = min(char_x + char_width, final_width)
                    end_y = min(char_y + char_height, final_height)
                    
                    if char_x >= 0 and char_y >= 0 and end_x > char_x and end_y > char_y:
                        # 获取字符的alpha掩码
                        alpha_mask = char_cache[char]
                        
                        # 调整掩码尺寸以匹配实际区域
                        actual_w = end_x - char_x
                        actual_h = end_y - char_y
                        
                        if actual_w != char_width or actual_h != char_height:
                            # 需要调整尺寸
                            alpha_resized = cv2.resize(alpha_mask, (actual_w, actual_h))
                        else:
                            alpha_resized = alpha_mask
                        
                        # 获取目标区域
                        target_region = out_image[char_y:end_y, char_x:end_x]
                        
                        # 使用alpha混合渲染字符
                        alpha_3d = np.stack([alpha_resized] * 3, axis=2)
                        colored_char = avg_color * alpha_3d
                        background = target_region * (1 - alpha_3d)
                        
                        # 混合结果
                        out_image[char_y:end_y, char_x:end_x] = (colored_char + background).astype(np.uint8)
    
    return out_image


def main_cached_ascii(opt, char_list, num_chars, bg_code, fps, final_width, final_height):
    """
    缓存ASCII处理 - 预渲染字符缓存，真实字符 + 高性能
    """
    cap = cv2.VideoCapture(opt.input)
    
    # 获取视频信息
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    height, width = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    
    print(f"缓存ASCII模式启动!")
    print(f"视频: {width}x{height}, {total_frames}帧")
    
    # 创建字体 - 稍微增大字符尺寸
    font_size = max(10, int(14 * opt.scale))  # 最小14像素，默认18像素
    font = ImageFont.truetype("fonts/DejaVuSansMono-Bold.ttf", size=font_size)
    left, top, right, bottom = font.getbbox("A")
    char_width = right - left
    char_height = bottom - top
    
    # 创建字符缓存（关键优化！）
    char_cache = create_char_cache(char_list, font, char_width, char_height, bg_code)
    
    # 智能网格计算 - 根据字符大小调整
    max_cols = final_width // char_width  # 根据字符宽度计算最大列数
    num_cols = min(opt.num_cols, max_cols, 100)  # 限制最大列数
    num_rows = max(1, final_height // (char_height + 2))  # 留一点间距
    
    # 确保合理的网格大小
    if num_cols * char_width > final_width:
        num_cols = final_width // char_width
    if num_rows * char_height > final_height:
        num_rows = final_height // char_height
    
    cell_width = width / num_cols
    cell_height = height / num_rows
    
    print(f"🎯 ASCII网格: {num_cols}x{num_rows}字符")
    print(f"📏 字符尺寸: {char_width}x{char_height}px")
    
    # 创建视频写入器 - 使用浏览器兼容的编码
    # 尝试H264，如果不可用则使用XVID
    try:
        fourcc = cv2.VideoWriter_fourcc(*'H264')
        out = cv2.VideoWriter(opt.output, fourcc, fps, (final_width, final_height))
        if not out.isOpened():
            raise Exception("H264 not available")
    except:
        print("⚠️ H264编码不可用，使用XVID编码")
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        # 更改文件扩展名为.avi以匹配XVID
        opt.output = opt.output.replace('.mp4', '.avi')
        out = cv2.VideoWriter(opt.output, fourcc, fps, (final_width, final_height))
    
    # 优化的并行设置
    available_cores = multiprocessing.cpu_count()
    batch_size = min(available_cores * 2, 16)  # 平衡批次大小
    
    print(f"💪 使用 {available_cores} 核心, 批次: {batch_size}")
    
    processed_frames = 0
    start_time = time.time()
    
    # 高效并行处理
    with ThreadPoolExecutor(max_workers=available_cores) as executor:
        while True:
            # 读取批次帧
            frames_batch = []
            original_frames = []
            
            for _ in range(batch_size):
                ret, frame = cap.read()
                if not ret:
                    break
                frames_batch.append(frame)
                if opt.overlay_ratio > 0:
                    original_frames.append(frame.copy())
            
            if not frames_batch:
                break
            
            # 使用缓存字符渲染
            process_func = partial(
                process_frame_cached_chars,
                char_list=char_list,
                num_chars=num_chars,
                num_cols=num_cols,
                num_rows=num_rows,
                cell_width=cell_width,
                cell_height=cell_height,
                final_width=final_width,
                final_height=final_height,
                bg_code=bg_code,
                char_cache=char_cache,
                char_width=char_width,
                char_height=char_height
            )
            
            # 并行提交所有帧
            futures = [executor.submit(process_func, frame) for frame in frames_batch]
            
            # 快速收集并写入
            for i, future in enumerate(futures):
                result_frame = future.result()
                
                # 快速叠加层
                if opt.overlay_ratio > 0 and i < len(original_frames):
                    h, w = result_frame.shape[:2]
                    overlay_h, overlay_w = int(h * opt.overlay_ratio), int(w * opt.overlay_ratio)
                    overlay = cv2.resize(original_frames[i], (overlay_w, overlay_h))
                    result_frame[h - overlay_h:, w - overlay_w:] = overlay
                
                out.write(result_frame)
                processed_frames += 1
                
                # 进度显示
                if processed_frames % 60 == 0:
                    progress = processed_frames / total_frames * 100
                    elapsed = time.time() - start_time
                    speed = processed_frames / elapsed if elapsed > 0 else 0
                    eta = (total_frames - processed_frames) / speed if speed > 0 else 0
                    print(f"🚀 缓存进度: {progress:.1f}% ({processed_frames}/{total_frames}) "
                          f"速度: {speed:.1f}fps, 预计完成: {eta:.0f}s")
    
    cap.release()
    out.release()
    
    total_time = time.time() - start_time
    avg_fps = total_frames / total_time if total_time > 0 else 0
    print(f"缓存处理完成! 用时: {total_time:.1f}s, 平均速度: {avg_fps:.1f}fps")
    print(f"输出: {opt.output}")
    
    # 性能分析
    if total_time > 90:  # 超过1.5分钟
        print("性能提示: 处理时间较长，建议:")
        print("   1. 降低num_cols参数 (建议50-80)")
        print("   2. 减少overlay_ratio")
        print("   3. 使用mode='simple'")
    elif total_time < 45:  # 小于45秒
        print("性能优秀! 缓存系统工作完美!")


def main(opt):
    if opt.mode == "simple":
        CHAR_LIST = '@%#*+=-:. '
    else:
        CHAR_LIST = r"$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,\"^`'. "
    if opt.background == "white":
        bg_code = (255, 255, 255)
    else:
        bg_code = (0, 0, 0)
    
    cap = cv2.VideoCapture(opt.input)
    if opt.fps == 0:
        fps = int(cap.get(cv2.CAP_PROP_FPS))
    else:
        fps = opt.fps
    num_chars = len(CHAR_LIST)
    
    # 获取原始视频尺寸
    original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # 确定最终输出尺寸
    if opt.target_width and opt.target_height:
        final_width, final_height = opt.target_width, opt.target_height
    elif opt.keep_aspect_ratio:
        if opt.target_width:
            final_width = opt.target_width
            final_height = int(opt.target_width * original_height / original_width)
        elif opt.target_height:
            final_height = opt.target_height
            final_width = int(opt.target_height * original_width / original_height)
        else:
            final_width, final_height = original_width, original_height
    else:
        final_width, final_height = None, None  # 使用传统模式
    
    # 直接使用缓存ASCII模式
    if final_width and final_height:
        return main_cached_ascii(opt, CHAR_LIST, num_chars, bg_code, fps, 
                                final_width, final_height)
    
    # 传统模式（保持原有逻辑）
    font = ImageFont.truetype("fonts/DejaVuSansMono-Bold.ttf", size=int(10 * opt.scale))
    
    while cap.isOpened():
        flag, frame = cap.read()
        if not flag:
            break
        height, width, _ = frame.shape
        
        # 如果指定了最终尺寸，重新计算字符参数以填满整个画面
        if final_width and final_height:
            # 获取字符尺寸
            left, top, right, bottom = font.getbbox("A")
            char_width = right - left
            char_height = bottom - top
            
            # 计算能够填满目标尺寸的字符数量
            num_cols = max(1, final_width // char_width)
            num_rows = max(1, final_height // (char_height * 2))  # 保持2倍高度比例
            
            # 重新计算单元格尺寸以适应原始视频
            cell_width = width / num_cols
            cell_height = height / num_rows
            
            # 创建目标尺寸的画布
            out_image = Image.new("RGB", (final_width, final_height), bg_code)
            draw = ImageDraw.Draw(out_image)
            
            # 计算字符在画布上的实际间距
            actual_char_width = final_width / num_cols
            actual_char_height = final_height / num_rows
            
            for i in range(num_rows):
                for j in range(num_cols):
                    # 从原始帧中提取对应区域
                    partial_image = frame[int(i * cell_height):min(int((i + 1) * cell_height), height),
                                    int(j * cell_width):min(int((j + 1) * cell_width), width), :]
                    
                    if partial_image.size > 0:  # 确保区域不为空
                        partial_avg_color = np.mean(partial_image, axis=(0, 1)).astype(np.int32)
                        partial_avg_color = tuple(partial_avg_color.tolist())
                        char = CHAR_LIST[min(int(np.mean(partial_image) * num_chars / 255), num_chars - 1)]
                        
                        # 在画布上绘制字符，居中对齐
                        x = int(j * actual_char_width + (actual_char_width - char_width) / 2)
                        y = int(i * actual_char_height + (actual_char_height - char_height) / 2)
                        draw.text((x, y), char, fill=partial_avg_color, font=font)
        else:
            # 传统模式
            cell_width = width / opt.num_cols
            cell_height = 2 * cell_width
            num_rows = int(height / cell_height)
            num_cols = opt.num_cols
            
            if num_cols > width or num_rows > height:
                print("Too many columns or rows. Use default setting")
                cell_width = 6
                cell_height = 12
                num_cols = int(width / cell_width)
                num_rows = int(height / cell_height)
            
            left, top, right, bottom = font.getbbox("A")
            char_width = right - left
            char_height = bottom - top
            out_width = char_width * num_cols
            out_height = 2 * char_height * num_rows
            out_image = Image.new("RGB", (out_width, out_height), bg_code)
            draw = ImageDraw.Draw(out_image)
            
            for i in range(num_rows):
                for j in range(num_cols):
                    partial_image = frame[int(i * cell_height):min(int((i + 1) * cell_height), height),
                                    int(j * cell_width):min(int((j + 1) * cell_width), width), :]
                    partial_avg_color = np.sum(np.sum(partial_image, axis=0), axis=0) / (cell_height * cell_width)
                    partial_avg_color = tuple(partial_avg_color.astype(np.int32).tolist())
                    char = CHAR_LIST[min(int(np.mean(partial_image) * num_chars / 255), num_chars - 1)]
                    draw.text((j * char_width, i * char_height), char, fill=partial_avg_color, font=font)

            # 传统模式的裁剪逻辑
            if opt.background == "white":
                cropped_image = ImageOps.invert(out_image).getbbox()
            else:
                cropped_image = out_image.getbbox()
            if cropped_image:
                out_image = out_image.crop(cropped_image)
        
        out_image = np.array(out_image)
        try:
            out
        except:
            out = cv2.VideoWriter(opt.output, cv2.VideoWriter_fourcc(*"H264"), fps,
                                  ((out_image.shape[1], out_image.shape[0])))

        if opt.overlay_ratio:
            height, width, _ = out_image.shape
            overlay = cv2.resize(frame, (int(width * opt.overlay_ratio), int(height * opt.overlay_ratio)))
            out_image[height - int(height * opt.overlay_ratio):, width - int(width * opt.overlay_ratio):, :] = overlay
        out.write(out_image)
    cap.release()
    out.release()


@video.post("/convert_video/")
async def convert_video(
    file: UploadFile = File(...),
    mode: str = Form(default="complex"),
    background: str = Form(default="black"),
    num_cols: int = Form(default=100),
    scale: int = Form(default=1),
    overlay_ratio: float = Form(default=0.2)
):
    # 创建独一无二的输入文件名
    input_file_location = f"data/{str(uuid.uuid4())}.mp4"

    # 将上传的文件保存到服务器
    with open(input_file_location, "wb") as f:
        content = await file.read()
        f.write(content)

    # 🎬 自动解析视频信息
    cap = cv2.VideoCapture(input_file_location)
    
    # 获取原始视频参数
    original_fps = int(cap.get(cv2.CAP_PROP_FPS))
    original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    cap.release()
    
    print(f"📹 视频信息解析完成:")
    print(f"   尺寸: {original_width} x {original_height}")
    print(f"   帧率: {original_fps} fps")
    print(f"   总帧数: {total_frames} 帧")
    print(f"   时长: {total_frames/original_fps:.1f} 秒")

    # 获取处理参数（自动使用原始视频参数）
    args = get_args(
        input_file_path=input_file_location,
        mode=mode,
        background=background,
        num_cols=num_cols,
        scale=scale,
        fps=original_fps,  # 🎯 使用原始帧率
        overlay_ratio=overlay_ratio,
        keep_aspect_ratio=True,  # 🎯 强制保持宽高比
        target_width=original_width,  # 🎯 使用原始宽度
        target_height=original_height  # 🎯 使用原始高度
    )

    try:
        # 调用主处理逻辑
        main(args)
        
        # 清理输入文件
        if os.path.exists(input_file_location):
            os.remove(input_file_location)
        
        # 返回详细的处理结果信息
        return JSONResponse(content={
            "absolute_path": os.path.abspath(args.output),
            "video_info": {
                "original_width": original_width,
                "original_height": original_height,
                "original_fps": original_fps,
                "total_frames": total_frames,
                "duration_seconds": round(total_frames/original_fps, 1)
            },
            "processing_info": {
                "mode": mode,
                "background": background,
                "num_cols": num_cols,
                "scale": scale,
                "overlay_ratio": overlay_ratio
            }
        })
    except Exception as e:
        # 清理输入文件
        if os.path.exists(input_file_location):
            os.remove(input_file_location)
        return JSONResponse(content={"error": str(e)}, status_code=500)




# 简化的同步视频处理函数（用于在线程池中运行）
def process_video_sync(file_path: str, args: Args, task_id: str):
    """同步处理视频转换任务（在线程池中运行）"""
    try:
        print(f"开始处理任务: {task_id}")
        
        # 确定字符集
        if args.mode == "simple":
            CHAR_LIST = '@%#*+=-:. '
        else:
            CHAR_LIST = r"$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,\"^`'. "
        
        if args.background == "white":
            bg_code = (255, 255, 255)
        else:
            bg_code = (0, 0, 0)
        
        cap = cv2.VideoCapture(args.input)
        if args.fps == 0:
            fps = int(cap.get(cv2.CAP_PROP_FPS))
        else:
            fps = args.fps
        num_chars = len(CHAR_LIST)
        
        # 获取原始视频尺寸
        original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        
        # 确定最终输出尺寸
        if args.target_width and args.target_height:
            final_width, final_height = args.target_width, args.target_height
        elif args.keep_aspect_ratio:
            if args.target_width:
                final_width = args.target_width
                final_height = int(args.target_width * original_height / original_width)
            elif args.target_height:
                final_height = args.target_height
                final_width = int(args.target_height * original_width / original_height)
            else:
                final_width, final_height = original_width, original_height
        else:
            final_width, final_height = original_width, original_height
        
        print(f"📐 目标尺寸: {final_width}x{final_height}")
        
        # 使用现有的main_cached_ascii函数处理视频
        main_cached_ascii(args, CHAR_LIST, num_chars, bg_code, fps, final_width, final_height)
        
        # 注意：音频处理将在异步环境中进行，这里只返回无音频版本的路径
        
        print(f"ASCII视频生成完成: {task_id}")
        return {
            "status": "completed",
            "output_path": args.output,
            "input_path": file_path,  # 保留原始文件路径用于音频处理
            "video_url": f"https://ascii.gyq-me.top/video/download/{os.path.basename(args.output)}"
        }
        
    except Exception as e:
        print(f"任务失败: {task_id}, 错误: {str(e)}")
        # 清理输入文件
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return {
            "status": "error",
            "error": str(e)
        }


# WebSocket处理视频转换的异步任务
async def process_video_task(file_path: str, args: Args, task_id: str):
    """异步处理视频转换任务"""
    try:
        await manager.send_progress(task_id, 0, "任务已启动，开始处理...")
        
        # 在线程池中运行同步的视频处理
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # 定期发送进度更新
            loop = asyncio.get_event_loop()
            
            # 启动视频处理任务
            future = executor.submit(process_video_sync, file_path, args, task_id)
            
            # 模拟进度更新（因为实际处理在另一个线程中）
            progress = 5
            while not future.done():
                await asyncio.sleep(2)  # 每2秒更新一次
                progress = min(progress + 5, 82)  # 逐步增加到82%，为音频处理留出空间
                await manager.send_progress(task_id, progress, f"处理中...({progress}%)")
            
            # 获取处理结果
            result = future.result()
            
            if result["status"] == "completed":
                # ASCII 视频生成完成，现在处理音频
                ascii_video_path = result["output_path"]
                original_video_path = result["input_path"]
                
                # 开始音频处理
                await manager.send_progress(task_id, 83, "开始音频处理...")
                
                # 异步处理音频合并
                final_video_path = await process_audio_async(original_video_path, ascii_video_path, task_id)
                
                # 清理原始输入文件
                if os.path.exists(original_video_path):
                    os.remove(original_video_path)
                
                # 更新最终结果
                final_video_url = f"https://ascii.gyq-me.top/video/download/{os.path.basename(final_video_path)}"
                
                # 发送完成消息
                await manager.send_progress(task_id, 98, "处理完成！")
                await asyncio.sleep(0.5)
                
                await manager.send_completed(task_id, final_video_url)
                
                # 更新任务状态
                final_result = result.copy()
                final_result["output_path"] = final_video_path
                final_result["video_url"] = final_video_url
                task_status[task_id] = final_result
            else:
                await manager.send_error(task_id, result["error"])
                task_status[task_id] = result
        
    except Exception as e:
        print(f"异步任务失败: {task_id}, 错误: {str(e)}")
        # 清理输入文件
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # 发送错误消息
        await manager.send_error(task_id, str(e))
        
        # 更新任务状态
        task_status[task_id] = {
            "status": "error",
            "error": str(e)
        }


# WebSocket端点
@video.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await manager.connect(websocket, task_id)
    try:
        while True:
            # 保持连接活跃
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(task_id)


# 启动视频转换任务的API
@video.post("/convert_video_ws/")
async def convert_video_ws(
    file: UploadFile = File(...),
    mode: str = Form(default="complex"),
    background: str = Form(default="black"),
    num_cols: int = Form(default=80),
    scale: int = Form(default=1),
    overlay_ratio: float = Form(default=0.0)
):
    """启动WebSocket视频转换任务"""
    # 生成任务ID
    task_id = str(uuid.uuid4())
    
    # 创建输入文件
    input_file_location = f"data/{task_id}_input.mp4"
    
    # 保存上传的文件
    with open(input_file_location, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # 获取视频信息
    cap = cv2.VideoCapture(input_file_location)
    original_fps = int(cap.get(cv2.CAP_PROP_FPS))
    original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    
    print(f"接收到参数: mode={mode}, overlay_ratio={overlay_ratio}, num_cols={num_cols}")
    
    # 创建处理参数
    args = get_args(
        input_file_path=input_file_location,
        mode=mode,
        background=background,
        num_cols=num_cols,
        scale=scale,
        fps=original_fps,
        overlay_ratio=overlay_ratio,  # 使用前端传入的参数
        keep_aspect_ratio=True,
        target_width=original_width,
        target_height=original_height
    )
    
    # 初始化任务状态
    task_status[task_id] = {
        "status": "processing",
        "video_info": {
            "original_width": original_width,
            "original_height": original_height,
            "original_fps": original_fps,
            "total_frames": total_frames,
            "duration_seconds": round(total_frames/original_fps, 1)
        }
    }
    
    # 启动异步任务
    try:
        asyncio.create_task(process_video_task(input_file_location, args, task_id))
        print(f"任务已启动: {task_id}")
    except Exception as e:
        print(f"启动任务失败: {str(e)}")
        return JSONResponse(content={"error": f"启动任务失败: {str(e)}"}, status_code=500)
    
    return {"task_id": task_id, "message": "任务已启动，请通过WebSocket连接获取进度"}


# 下载生成的视频
@video.get("/download/{filename}")
async def download_video(filename: str):
    """下载生成的视频文件"""
    file_path = f"data/{filename}"
    if os.path.exists(file_path):
        from fastapi.responses import FileResponse
        response = FileResponse(
            path=file_path,
            filename=filename,
            media_type='video/mp4'
        )
        # 添加CORS头支持视频播放
        # response.headers["Access-Control-Allow-Origin"] = "*"
        # response.headers["Access-Control-Allow-Methods"] = "GET"
        # response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Accept-Ranges"] = "bytes"
        return response
    else:
        return JSONResponse(content={"error": "文件不存在"}, status_code=404)


# 手动清理命令（可选）
@video.post("/manual_cleanup/")
async def manual_cleanup():
    """手动触发清理过期视频文件"""
    await cleanup_old_videos()
    return {"message": "手动清理任务已执行"}

# 获取清理状态
@video.get("/cleanup_status/")
async def cleanup_status():
    """获取定时清理状态信息"""
    data_dir = "data/"
    if not os.path.exists(data_dir):
        return {"status": "data目录不存在", "files": 0, "total_size": 0}
    
    media_files = []
    total_size = 0
    
    media_patterns = [
        os.path.join(data_dir, "*.mp4"),
        os.path.join(data_dir, "*.avi"),
        os.path.join(data_dir, "*.mov"),
        os.path.join(data_dir, "*.jpg"),
        os.path.join(data_dir, "*.jpeg"),
        os.path.join(data_dir, "*.png")
    ]
    
    for pattern in media_patterns:
        for file_path in glob.glob(pattern):
            try:
                file_size = os.path.getsize(file_path)
                file_mtime = os.path.getmtime(file_path)
                file_age_hours = (datetime.now().timestamp() - file_mtime) / 3600
                
                media_files.append({
                    "filename": os.path.basename(file_path),
                    "size_mb": round(file_size / 1024 / 1024, 2),
                    "age_hours": round(file_age_hours, 1),
                    "will_be_deleted": file_age_hours > 24
                })
                total_size += file_size
            except Exception as e:
                print(f"获取文件信息失败 {file_path}: {str(e)}")
    
    return {
        "scheduler_running": scheduler.running,
        "total_files": len(media_files),
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "files": media_files,
        "next_cleanup": "每天凌晨2点"
    }

# 启动定时清理调度器
try:
    start_cleanup_scheduler()
except Exception as e:
    print(f"定时清理调度器启动失败: {str(e)}")

# 运行应用
# uvicorn your_script_name:app --reload
