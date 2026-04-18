from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "petcam-lab is alive"}

@app.get("/health")
def health():
    return {"status": "ok"}
