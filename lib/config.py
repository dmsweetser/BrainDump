import os
from pathlib import Path

from dotenv import load_dotenv

class Config:
    
    load_dotenv()
    
    # App Settings
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

    # Database
    DATABASE = os.getenv("DATABASE", "brain_dump.db")
    HTML_OUTPUT = os.getenv("HTML_OUTPUT", "output")

    # AI Model
    USE_LOCAL_MODEL = os.getenv("USE_LOCAL_MODEL", "False").lower() == "true"
    MODEL_PATH = os.getenv("MODEL_PATH")
    ENDPOINT = os.getenv("ENDPOINT")
    MODEL_NAME = os.getenv("MODEL_NAME")
    API_KEY = os.getenv("API_KEY")
    TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))
    TOP_P = float(os.getenv("TOP_P", 0.9))
    TOP_K = int(os.getenv("TOP_K", 40))
    MIN_P = float(os.getenv("MIN_P", 0.05))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", 2048))
    CONTEXT_SIZE = int(os.getenv("CONTEXT_SIZE", 4096))

    # Email
    SMTP_ENABLED = os.getenv("SMTP_ENABLED", "False").lower() == "true"
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    EMAIL_SENDER = os.getenv("EMAIL_SENDER")
    EMAIL_RECIPIENTS = os.getenv("EMAIL_RECIPIENTS", "").split(",")

    # Revision Queue
    REVISION_QUEUE_ENABLED = True
    REVISION_QUEUE_DELAY = float(os.getenv("REVISION_QUEUE_DELAY", 1.0))  # seconds

    # Utility
    @staticmethod
    def get_root_directory() -> Path:
        return Path(__file__).parent.resolve()

    @staticmethod
    def get_ai_builder_dir(root_dir: Path) -> Path:
        return root_dir / "ai_builder"

    @staticmethod
    def get_log_file_path(root_dir: Path) -> str:
        return str(root_dir / "ai_builder" / "brain_dump.log")

    @staticmethod
    def generate_output_only() -> bool:
        return os.getenv("GENERATE_OUTPUT_ONLY", "False").lower() == "true"

    @staticmethod
    def generate_but_do_not_apply() -> bool:
        return os.getenv("GENERATE_BUT_DO_NOT_APPLY", "False").lower() == "true"