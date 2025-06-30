"""
@author: Viet Nguyen <nhviet1009@gmail.com>
"""
import argparse
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse

from utils import get_data

image = APIRouter()


def get_args():
    parser = argparse.ArgumentParser("Image to ASCII")
    parser.add_argument("--input", type=str, default="data/input.jpg", help="Path to input image")
    parser.add_argument("--output", type=str, default="data/output.jpg", help="Path to output text file")
    parser.add_argument("--language", type=str, default="english",
                        choices=["general", "english", "german", "french", "italian", "polish", "portuguese"])
    parser.add_argument("--mode", type=str, default="standard")
    parser.add_argument("--background", type=str, default="black", choices=["black", "white"],
                        help="background's color")
    parser.add_argument("--num_cols", type=int, default=300, help="number of character for output's width")
    parser.add_argument("--scale", type=int, default=2, help="upsize output")
    args = parser.parse_args()
    return args


def process_row(i, num_cols, cell_height, cell_width, char_list, num_chars, char_width, char_height, font, image):
    row_result = []
    for j in range(num_cols):
        partial_image = image[int(i * cell_height):min(int((i + 1) * cell_height), image.shape[0]),
                        int(j * cell_width):min(int((j + 1) * cell_width), image.shape[1]), :]
        partial_avg_color = np.mean(partial_image, axis=(0, 1)).astype(np.int32).tolist()
        char = char_list[min(int(np.mean(partial_image) * num_chars / 255), num_chars - 1)]
        row_result.append((j * char_width, i * char_height, char, tuple(partial_avg_color)))
    return row_result


def main(opt):
    start_time = time.time()
    logging.info("开始处理图片")
    if opt.background == "white":
        bg_code = (255, 255, 255)
    else:
        bg_code = (0, 0, 0)

    # 获取字符数据并检查None值
    data_result = get_data(opt.language, opt.mode)
    if data_result is None or len(data_result) != 4:
        raise ValueError(f"无法获取语言 '{opt.language}' 和模式 '{opt.mode}' 的字符数据")
    
    char_list, font, sample_character, scale = data_result
    
    # 检查返回值是否为None
    if char_list is None or font is None or sample_character is None or scale is None:
        raise ValueError("字符数据包含空值，无法继续处理")
    
    logging.info("字符数据加载完成")
    num_chars = len(char_list)
    num_cols = opt.num_cols

    # 图像加载与预处理
    image = cv2.imread(opt.input, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片文件: {opt.input}")
    
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width, _ = image.shape
    logging.info("图片加载并转换为RGB格式完成")

    # 计算每个单元格的宽度、高度和行列数量
    cell_width = width / num_cols
    cell_height = scale * cell_width
    num_rows = int(height / cell_height)
    if num_cols > width or num_rows > height:
        print("Too many columns or rows. Use default setting")
        cell_width = 6
        cell_height = 12
        num_cols = int(width / cell_width)
        num_rows = int(height / cell_height)

    # 输出图像初始化
    bbox = font.getbbox(sample_character)
    char_width = bbox[2] - bbox[0]
    char_height = bbox[3] - bbox[1]
    out_width = int(char_width * num_cols)
    out_height = int(scale * char_height * num_rows)
    out_image = Image.new("RGB", (out_width, out_height), bg_code)
    draw = ImageDraw.Draw(out_image)
    logging.info("输出图片初始化完成")

    row_start_time = time.time()
    # 并行处理每一行
    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(process_row, i, num_cols, cell_height, cell_width, char_list, num_chars,
                            char_width, char_height, font, image)
            for i in range(num_rows)
        ]

        # 合并结果
        for future in as_completed(futures):
            row_data = future.result()
            for x, y, char, color in row_data:
                draw.text((x, y), char, fill=color, font=font)
    logging.info(f"所有行处理完成，耗时：{time.time() - row_start_time:.2f}秒")
    crop_start_time = time.time()
    # 裁剪图像并保存
    if opt.background == "white":
        cropped_image = ImageOps.invert(out_image).getbbox()
    else:
        cropped_image = out_image.getbbox()
    
    if cropped_image:
        out_image = out_image.crop(cropped_image)
    
    out_image.save(opt.output)
    logging.info(f"裁剪并保存图片完成，耗时：{time.time() - crop_start_time:.2f}秒")

    logging.info(f"总处理时间：{time.time() - start_time:.2f}秒")


class Opt:
    def __init__(self, input_file_path: str, language: str, mode: str, background: str):
        self.input = input_file_path
        self.language = language
        self.mode = mode
        self.background = background
        self.output = f"data/{str(uuid.uuid4())}.jpg"  # 动态生成唯一的输出路径
        self.num_cols = 300  # 示例参数，根据需要调整


@image.post("/convert_image")
async def convert_image(file: UploadFile = File(...),
                        language: str = Form(...),
                        mode: str = Form(...),
                        background: str = Form("black")):
    # 本地临时保存输入文件
    input_file_location = f"data/{str(uuid.uuid4())}_input.jpg"
    
    try:
        with open(input_file_location, "wb") as f:
            content = await file.read()
            f.write(content)

        # 处理图片
        opt = Opt(input_file_path=input_file_location, language=language, mode=mode, background=background)
        main(opt)

        # 生成下载链接
        output_filename = os.path.basename(opt.output)
        image_url = f"https://ascii.gyq-me.top/image/download/{output_filename}"
        
        # 清理输入文件
        if os.path.exists(input_file_location):
            os.remove(input_file_location)

        return JSONResponse(content={
            "image_url": image_url,
            "absolute_path": os.path.abspath(opt.output),
            "processing_info": {
                "language": language,
                "mode": mode,
                "background": background
            }
        })
    
    except Exception as e:
        # 清理输入文件
        if os.path.exists(input_file_location):
            os.remove(input_file_location)
        return JSONResponse(content={"error": str(e)}, status_code=500)


# 下载生成的图片
@image.get("/download/{filename}")
async def download_image(filename: str):
    """下载生成的图片文件"""
    file_path = f"data/{filename}"
    if os.path.exists(file_path):
        response = FileResponse(
            path=file_path,
            filename=filename,
            media_type='image/jpeg'
        )
        # # 添加CORS头支持图片显示
        # response.headers["Access-Control-Allow-Origin"] = "*"
        # response.headers["Access-Control-Allow-Methods"] = "GET"
        # response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    else:
        return JSONResponse(content={"error": "文件不存在"}, status_code=404)
