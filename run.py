import uvicorn

if __name__ == "__main__":
    uvicorn.run("jobagent.app:build_app", factory=True, host="127.0.0.1", port=8000)
