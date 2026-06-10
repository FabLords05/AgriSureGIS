from fastapi import FastAPI

app = FastAPI(title="AgriSureGIS Backend")

@app.get("/")
def read_root():
    return {"status": "AgriSureGIS Engine Active"}
