"""Central configuration. Everything runs on free tiers / local compute."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
VECTOR_DIR = DATA_DIR / "vectors"
DATA_DIR.mkdir(exist_ok=True)
VECTOR_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'vidsage.db'}")

# --- Auth ---
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days

# --- LLM (all free tiers) ---
# provider: "groq" (free, fastest) or "huggingface" (free)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_MODEL = os.getenv("HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
HF_URL = "https://router.huggingface.co/v1/chat/completions"

# --- Embeddings (local, free, no API key) ---
# Multilingual model: Bangla, English, Hindi and 50+ languages share one vector space,
# so you can ask in one language about a video spoken in another.
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)

# --- Voice (Whisper, runs locally, free) ---
# Sizes: tiny / base / small — "base" is a good accuracy/speed balance on CPU.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# --- RAG ---
CHUNK_SIZE = 1100          # characters per chunk
CHUNK_OVERLAP = 200
TOP_K = 4                  # retrieved chunks per question
MAX_CONTEXT_CHARS = 9000   # safety cap for summary/quiz prompts
