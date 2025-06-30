+ 创建虚拟环境
  + python -m venv venv
  + source venv/bin/activate
+ 下载依赖
  + pip install -r requirements.txt
+ 启动服务
  + uvicorn app:app --host 0.0.0.0 --port 8000