"""
@author: Viet Nguyen <nhviet1009@gmail.com>
"""
import argparse
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from utils import get_data
import os
from fastapi import FastAPI, File, UploadFile, APIRouter
from fastapi.responses import JSONResponse

image = APIRouter()


def get_args():
    parser = argparse.ArgumentParser("Image to ASCII")
    parser.add_argument("--input", type=str, default="data/input.jpg", help="Path to input image")
    parser.add_argument("--output", type=str, default="data/output.jpg", help="Path to output text file")
    parser.add_argument("--language", type=str, default="english")
    parser.add_argument("--mode", type=str, default="standard")
    parser.add_argument("--background", type=str, default="black", choices=["black", "white"],
                        help="background's color")
    parser.add_argument("--num_cols", type=int, default=300, help="number of characters for output's width")
    parser.add_argument("--preserve_aspect_ratio", action="store_true", help="Preserve original aspect ratio")
    args = parser.parse_args()
    return args


def main(opt):
    if opt.background == "white":
        bg_code = 255
    else:
        bg_code = 0
    char_list, font, sample_character, scale = get_data(opt.language, opt.mode)
    num_chars = len(char_list)
    num_cols = opt.num_cols
    image = cv2.imread(opt.input)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = image.shape

    cell_width = width / num_cols
    if opt.preserve_aspect_ratio:
        cell_height = cell_width / (width / height)
    else:
        cell_height = scale * cell_width

    num_rows = int(height / cell_height)
    if num_cols > width or num_rows > height:
        print("Too many columns or rows. Use default setting")
        cell_width = 6
        cell_height = 12
        num_cols = int(width / cell_width)
        num_rows = int(height / cell_height)

    char_width, char_height = font.getsize(sample_character)
    out_width = char_width * num_cols
    out_height = scale * char_height * num_rows
    out_image = Image.new("L", (out_width, out_height), bg_code)
    draw = ImageDraw.Draw(out_image)

    for i in range(num_rows):
        line = "".join([char_list[min(int(np.mean(image[int(i * cell_height):min(int((i + 1) * cell_height), height),
                                                  int(j * cell_width):min(int((j + 1) * cell_width),
                                                                          width)]) / 255 * num_chars), num_chars - 1)]
                        for j in
                        range(num_cols)]) + "\n"
        draw.text((0, i * char_height), line, fill=255 - bg_code, font=font)

    if opt.background == "white":
        cropped_image = ImageOps.invert(out_image).getbbox()
    else:
        cropped_image = out_image.getbbox()

    out_image = out_image.crop(cropped_image)
    out_image.save(opt.output)


@image.post("/changeImage")
async def convert_image(file: UploadFile = File(...)):
    try:
        input_path = "temp_input.jpg"
        output_path = "temp_output.jpg"

        # Save the uploaded file to a temporary location
        with open(input_path, "wb") as f:
            f.write(await file.read())

        # Prepare arguments for the main function
        class Opt:
            input = input_path
            output = output_path
            language = "english"
            mode = "standard"
            background = "black"
            num_cols = 300
            preserve_aspect_ratio = True

        opt = Opt()
        main(opt)

        return JSONResponse(content={"output_path": os.path.abspath(output_path)})

    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


if __name__ == '__main__':
    opt = get_args()
    main(opt)
