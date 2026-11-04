"""AWS Lambda entry point. Uvicorn continues to import app.main:app locally."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
