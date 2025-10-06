# BrainDump
A Flask application for managing and organizing notes with LLM-powered structuring

## Sample .env

```
SECRET_KEY=your-super-secret-key-here
DEBUG=True

DATABASE=brain_dump.db
HTML_OUTPUT=output
SYSTEM_PROMPT_FILE=system_prompt.txt

USE_LOCAL_MODEL=False
MODEL_PATH=/path/to/llama-3-8b.gguf
API_KEY=
ENDPOINT=
MODEL_NAME=
TEMPERATURE=0.7
TOP_P=0.9
TOP_K=40
MIN_P=0.05
MAX_TOKENS=32768
CONTEXT_SIZE=131072

SMTP_ENABLED=False
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_SENDER=you@gmail.com
EMAIL_RECIPIENTS=friend@example.com,team@company.com
```