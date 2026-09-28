import uvicorn
from pcb_assistant.api import create_app

app = create_app()
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info"))


@app.post("/api/shutdown")
def shutdown():
    server.should_exit = True
    return {"status": "stopping"}


if __name__ == "__main__":
    server.run()
