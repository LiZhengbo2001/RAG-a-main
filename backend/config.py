import os
from pathlib import Path
from dotenv import load_dotenv
import secrets

load_dotenv(Path(__file__).parent / ".env")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+aiomysql://root:123456@localhost:3306/rag_agent")

# Milvus Server
MILVUS_SERVER = os.getenv("MILVUS_SERVER", "http://host.docker.internal:19530")
MILVUS_DATABASE_NAME = os.getenv("MILVUS_DATABASE_NAME", "RAG")
MILVUS_COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "collection")
MILVUS_VECTOR_DIMENSION = int(os.getenv("MILVUS_VECTOR_DIMENSION", "768"))

# LLM
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen2.5:7b")
LLM_AGENT_MODEL_NAME = os.getenv("LLM_AGENT_MODEL_NAME", "qwen2.5:7b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))

# Embedding
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-large-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

# Document
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./storage/documents")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "64"))

# Retrieval
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "10"))

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 默认 24 小时

# ── 客服系统配置 ──
COMPANY_NAME = os.getenv("COMPANY_NAME", "公司")
CUSTOMER_SERVICE_PHONE = os.getenv("CUSTOMER_SERVICE_PHONE", "400-000-0000")
AGENT_NAME = os.getenv("AGENT_NAME", "小助手")
LEAD_TIMEOUT_SECONDS = int(os.getenv("LEAD_TIMEOUT_SECONDS", "5"))
SUGGESTED_QUESTIONS = os.getenv("SUGGESTED_QUESTIONS", "").split(",") if os.getenv("SUGGESTED_QUESTIONS") else []