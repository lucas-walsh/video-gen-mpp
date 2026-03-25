import os
from dotenv import load_dotenv

load_dotenv()

FAL_AI_KEY = os.getenv("FAL_AI_KEY", "")
FAL_QUEUE_BASE_URL = os.getenv("FAL_QUEUE_BASE_URL", "https://queue.fal.run")
MPP_SECRET_KEY = os.getenv("MPP_SECRET_KEY", "")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

MARKUP_PERCENT = 20  # 20% markup on Fal.ai costs
QUOTE_TTL_SECONDS = 300  # 5 minutes

SUPPORTED_VIDEO_MODELS = [
    "fal-ai/veo3.1/fast",  # Fast, cheap text-to-video
    "fal-ai/veo3.1",  # Standard text-to-video
    "fal-ai/kling-video/v3/standard/text-to-video",  # Kling 3.0
    "fal-ai/wan/v2.2-a14b/image-to-video",  # Wan (image-to-video only)
]

DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "fal-ai/veo3.1/fast")
