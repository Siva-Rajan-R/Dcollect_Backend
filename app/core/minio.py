from minio import Minio
from app.core.config import settings

class MinioClient:
    client: Minio = None

minio_client = MinioClient()

def connect_to_minio():
    minio_client.client = Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE
    )
    print("Connected to MinIO")

def get_minio_client() -> Minio:
    return minio_client.client
