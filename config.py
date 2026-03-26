"""
Configuration for Video Generation API with MPP.

Consolidated configuration using MPPConfig from mpp package.
"""

import os
from dotenv import load_dotenv
from mpp.config import MPPConfig, get_config

load_dotenv()

FAL_AI_KEY = os.getenv("FAL_AI_KEY", "")
FAL_QUEUE_BASE_URL = os.getenv("FAL_QUEUE_BASE_URL", "https://queue.fal.run")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

MARKUP_PERCENT = 20
QUOTE_TTL_SECONDS = 300

SUPPORTED_VIDEO_MODELS = [
    "fal-ai/veo3.1/fast",
    "fal-ai/veo3.1",
    "fal-ai/kling/video/v2.5/pro",
    "fal-ai/wan/v2.2-a14b/image-to-video",
]

DEFAULT_VIDEO_MODEL = os.getenv("DEFAULT_VIDEO_MODEL", "fal-ai/veo3.1/fast")


def get_mpp_config() -> MPPConfig:
    """Get MPP configuration from environment."""
    return get_config()


def get_fal_key() -> str:
    """Get FAL AI API key."""
    return FAL_AI_KEY
