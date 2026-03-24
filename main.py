import uuid
import time
import logging
from datetime import datetime, timezone
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import httpx

from config import FAL_AI_KEY, MARKUP_PERCENT, QUOTE_TTL_SECONDS, DEFAULT_VIDEO_MODEL, SUPPORTED_VIDEO_MODELS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


quote_sessions = {}


def cleanup_expired_sessions():
    now = time.time()
    expired = [sid for sid, data in quote_sessions.items() if data["expires_at"] < now]
    for sid in expired:
        del quote_sessions[sid]


def validate_generate_request(data):
    if "prompt" not in data:
        raise ValueError("prompt is required")
    if "duration_seconds" not in data:
        raise ValueError("duration_seconds is required")
    duration = data["duration_seconds"]
    if not isinstance(duration, (int, float)) or duration < 1 or duration > 30:
        raise ValueError("duration_seconds must be between 1 and 30")
    if not isinstance(data.get("prompt"), str) or not data["prompt"].strip():
        raise ValueError("prompt must be a non-empty string")
    model = data.get("model")
    if model is not None:
        if model not in SUPPORTED_VIDEO_MODELS:
            raise ValueError(f"model must be one of: {', '.join(SUPPORTED_VIDEO_MODELS)}")
    return data


async def get_fal_pricing(endpoint_id: str = "fal-ai/veo3.1/fast"):
    if not FAL_AI_KEY:
        return None, None
    
    url = "https://api.fal.ai/v1/models/pricing"
    headers = {"Authorization": f"Key {FAL_AI_KEY}"}
    params = {"endpoint_id": endpoint_id}
    
    logger.info(f"Fetching pricing from Fal.ai:")
    logger.info(f"  URL: {url}")
    logger.info(f"  Headers: Authorization: Key {FAL_AI_KEY[:8]}...")
    logger.info(f"  Params: {params}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, headers=headers, timeout=10.0)
            
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch pricing: HTTP {response.status_code}")
                return None, None
            
            data = response.json()
            logger.info(f"Parsed response data: {data}")
            
            prices = data.get("prices", [])
            if not prices:
                logger.error(f"No pricing information returned for endpoint: {endpoint_id}")
                return None, None
            
            # Find the price for our specific endpoint_id
            price_info = next(
                (p for p in prices if p.get("endpoint_id") == endpoint_id),
                prices[0]  # Fallback to first if not found
            )
            price = price_info.get("unit_price")
            unit = price_info.get("unit", "second")
            
            logger.info(f"Extracted pricing: price={price}, unit={unit}")
            return price, unit
            
    except httpx.TimeoutException as e:
        logger.error(f"Timeout fetching pricing from Fal.ai: {e}")
        return None, None
    except httpx.RequestError as e:
        logger.error(f"Request error fetching pricing from Fal.ai: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Unexpected error fetching pricing from Fal.ai: {e}")
        return None, None


def calculate_final_price(fal_price: float) -> float:
    return fal_price * (1 + MARKUP_PERCENT / 100)


def verify_payment_credential(credential: str, session_id: str) -> bool:
    if session_id not in quote_sessions:
        return False
    session = quote_sessions[session_id]
    if session["expires_at"] < time.time():
        del quote_sessions[session_id]
        return False
    if not credential:
        return False
    return True


async def generate_video(request):
    cleanup_expired_sessions()

    auth_header = request.headers.get("Authorization", "")
    payment_credential = None
    session_id = None

    if auth_header.startswith("Payment "):
        parts = auth_header.split(" ")
        if len(parts) == 2:
            payment_credential = parts[1]
            session_id = request.headers.get("X-Session-ID")

    if payment_credential and session_id:
        if verify_payment_credential(payment_credential, session_id):
            session = quote_sessions[session_id]
            job_id = f"job_{uuid.uuid4().hex}"
            del quote_sessions[session_id]

            return JSONResponse({
                "success": True,
                "job_id": job_id,
                "status": "processing",
                "cost_usd": session["final_price_total"],
                "message": "Payment verified. Video generation started.",
            }, headers={"Payment-Receipt": f"session={session_id}"})
        else:
            return JSONResponse({
                "success": False,
                "error": "Invalid or expired payment credential",
            }, status_code=401)

    try:
        data = await request.json()
        validate_generate_request(data)
    except (ValueError, Exception) as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=400)

    model = data.get("model", DEFAULT_VIDEO_MODEL)
    fal_price, unit = await get_fal_pricing(model)
    if fal_price is None:
        logger.error("Failed to fetch pricing from Fal.ai - returning 503")
        return JSONResponse({
            "success": False,
            "error": "Unable to fetch pricing from Fal.ai",
            "details": {
                "endpoint_id": model,
                "possible_causes": [
                    "Invalid or missing FAL_AI_KEY",
                    "Fal.ai API is temporarily unavailable",
                    "Network connectivity issue",
                ],
            },
        }, status_code=503)

    duration = data["duration_seconds"]
    fal_total = fal_price * duration
    final_price_total = calculate_final_price(fal_total)

    session_id = f"quote_{uuid.uuid4().hex[:12]}"
    quote_sessions[session_id] = {
        "prompt": data["prompt"],
        "duration_seconds": duration,
        "model": model,
        "fal_price_per_unit": fal_price,
        "unit": unit,
        "final_price_total": final_price_total,
        "expires_at": time.time() + QUOTE_TTL_SECONDS,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    response = JSONResponse({
        "success": False,
        "error": "Payment required",
        "session_id": session_id,
        "pricing": {
            "model": model,
            "price_per_unit": fal_price,
            "unit": unit,
            "duration_seconds": duration,
            "subtotal_usd": fal_total,
            "markup_percent": MARKUP_PERCENT,
            "final_price_total": round(final_price_total, 2),
        },
        "expires_in_seconds": QUOTE_TTL_SECONDS,
    }, status_code=402)

    response.headers["WWW-Authenticate"] = f'Payment realm="video-gen", session_id="{session_id}", amount="{final_price_total:.4f}"'

    return response


async def get_job(request):
    return JSONResponse({"status": "placeholder"})


async def get_gallery(request):
    return JSONResponse({"videos": [], "total": 0})


async def homepage(request):
    return JSONResponse({
        "name": "Video Generation API (MPP)",
        "version": "1.0.0",
        "endpoints": [
            "POST /api/video/generate",
            "GET /api/video/jobs/{job_id}",
            "GET /api/video/gallery",
        ],
    })


routes = [
    Route("/", homepage),
    Route("/api/video/generate", generate_video, methods=["POST"]),
    Route("/api/video/jobs/{job_id}", get_job, methods=["GET"]),
    Route("/api/video/gallery", get_gallery, methods=["GET"]),
]

app = Starlette(routes=routes)
