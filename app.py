from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from img2img_color import image
from video2video_color import video
app = FastAPI()

app.include_router(image, prefix="/image", tags=["图片模块"])
app.include_router(video, prefix="/video", tags=["视频模块"])


@app.get("/")
async def root():
    return {"message": "Hello World"}
