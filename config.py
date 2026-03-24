import os
from dotenv import load_dotenv

load_dotenv()

FAL_AI_KEY = os.getenv("FAL_AI_KEY", "")
MPP_SECRET_KEY = os.getenv("MPP_SECRET_KEY", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

MARKUP_PERCENT = 20  # 20% markup on Fal.ai costs
QUOTE_TTL_SECONDS = 300  # 5 minutes

SUPPORTED_VIDEO_MODELS = [
    "fal-ai/veo3.1/fast",
    "fal-ai/veo3.1",
    "fal-ai/luma-dream-machine",
    "fal-ai/kling-video/v1.5/pro",
]

DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "fal-ai/veo3.1/fast")
