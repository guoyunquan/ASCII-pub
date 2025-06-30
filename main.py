from app import app

if __name__ == "__main__":
    import uvicorn
    # import debugpy
    #
    # # 监听调试端口，默认 5678
    # debugpy.listen(("101.37.252.120", 5678))
    # print("Waiting for debugger to attach...")
    # debugpy.wait_for_client()  # 等待 IDE 连接

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
