from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Konfigurasi aplikasi.
    Pydantic Settings akan memuat variabel dari file .env
    """

    # --- Wajib ---
    SUPABASE_URL: str
    SUPABASE_KEY: str

    OPENAI_API_KEY: str
    PINECONE_API_KEY: str

    # --- Opsional (punya default) ---
    # OpenAI
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"  # 1536 dim

    # Pinecone (PC2 / serverless, host-based)
    PINECONE_INDEX_NAME: str = "chatbot-api"
    PINECONE_INDEX_HOST: Optional[str] = None  # contoh: chatbot-api-xxxxx.svc.<region>.pinecone.io (tanpa https://)
    PINECONE_NAMESPACE: str = "default"
    PINECONE_MIN_SCORE: float = 0.5

    # (Legacy/compat, tidak dipakai PC2—boleh dihapus jika tidak perlu)
    PINECONE_CLOUD: Optional[str] = None
    PINECONE_REGION: Optional[str] = None

    # Aplikasi
    APP_NAME: str = "Chatbot BAAK Hybrid"
    DEBUG: bool = False

    # Sesi
    SESSION_TIMEOUT_MINUTES: int = 30
    MAX_MEMORY_EXCHANGES: int = 3

    # Pydantic v2 config
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="forbid",  # tolak env yang tidak dideklarasikan (biar typo ketahuan)
    )

settings = Settings()