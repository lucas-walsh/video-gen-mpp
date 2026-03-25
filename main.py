import uuid
import time
import logging
import os
from datetime import datetime, timezone
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
import fal_client

from config import FAL_AI_KEY, MARKUP_PERCENT, QUOTE_TTL_SECONDS, DEFAULT_VIDEO_MODEL, SUPPORTED_VIDEO_MODELS
from asyncio import Lock

os.environ["FAL_KEY"] = FAL_AI_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


quote_sessions = {}
jobs_db = {}
last_poll_time = {}
POLL_CACHE_SECONDS = 5
jobs_lock = Lock()


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
        import httpx
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
            
            price_info = next(
                (p for p in prices if p.get("endpoint_id") == endpoint_id),
                prices[0]
            )
            price = price_info.get("unit_price")
            unit = price_info.get("unit", "second")
            
            logger.info(f"Extracted pricing: price={price}, unit={unit}")
            return price, unit
            
    except Exception as e:
        logger.error(f"Error fetching pricing from Fal.ai: {e}")
        return None, None
    
    url = "https://api.fal.ai/v1/models/pricing"
    headers = {"Authorization": f"Key {FAL_AI_KEY}"}
    params = {"endpoint_id": endpoint_id}
    
    logger.info(f"Fetching pricing from Fal.ai:")
    logger.info(f"  URL: {url}")
    logger.info(f"  Headers: Authorization: Key {FAL_AI_KEY[:8]}...")
    logger.info(f"  Params: {params}")
    
    try:
        import httpx
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
            
            price_info = next(
                (p for p in prices if p.get("endpoint_id") == endpoint_id),
                prices[0]
            )
            price = price_info.get("unit_price")
            unit = price_info.get("unit", "second")
            
            logger.info(f"Extracted pricing: price={price}, unit={unit}")
            return price, unit
            
    except Exception as e:
        logger.error(f"Error fetching pricing from Fal.ai: {e}")
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


async def submit_to_fal(model: str, prompt: str):
    try:
        handle = await fal_client.submit_async(
            model,
            arguments={"prompt": prompt}
        )
        return {"request_id": handle.request_id, "handle": handle}
    except fal_client.FalClientHTTPError as e:
        logger.error(f"FAL HTTP error: {e.status_code} - {e.message}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise


async def fetch_fal_job_status(endpoint_id: str, request_id: str):
    try:
        status = await fal_client.status_async(endpoint_id, request_id=request_id)
        return {"status": status}
    except fal_client.FalClientHTTPError as e:
        logger.error(f"FAL HTTP error: {e.status_code} - {e.message}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise


async def fetch_fal_job_result(endpoint_id: str, request_id: str):
    try:
        result = await fal_client.result_async(endpoint_id, request_id=request_id)
        return result
    except fal_client.FalClientHTTPError as e:
        logger.error(f"FAL HTTP error: {e.status_code} - {e.message}")
        raise
    except fal_client.FalClientError as e:
        logger.error(f"FAL client error: {e}")
        raise


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
        logger.info(f"Payment attempt: session_id={session_id}, credential={payment_credential}")
        logger.info(f"Sessions in memory: {list(quote_sessions.keys())}")
        logger.info(f"Session exists: {session_id in quote_sessions}")
        if verify_payment_credential(payment_credential, session_id):
            session = quote_sessions[session_id]
            job_id = f"job_{uuid.uuid4().hex}"
            model = session["model"]
            prompt = session["prompt"]
            del quote_sessions[session_id]

            try:
                fal_response = await submit_to_fal(model, prompt)
            except fal_client.FalClientHTTPError as e:
                logger.error(f"Failed to submit to Fal.ai: HTTP {e.status_code} - {e.message}")
                return JSONResponse({
                    "success": False,
                    "error": f"Failed to submit video generation request: {e.message}",
                    "status_code": e.status_code,
                }, status_code=503)
            except fal_client.FalClientError as e:
                logger.error(f"Failed to submit to Fal.ai: {e}")
                return JSONResponse({
                    "success": False,
                    "error": f"Failed to submit video generation request: {str(e)}",
                }, status_code=503)
            except fal_client.FalClientError as e:
                logger.error(f"Failed to submit to Fal.ai: {e}")
                return JSONResponse({
                    "success": False,
                    "error": f"Failed to submit video generation request: {str(e)}",
                }, status_code=503)

            jobs_db[job_id] = {
                "job_id": job_id,
                "request_id": fal_response["request_id"],
                "endpoint_id": model,
                "prompt": prompt,
                "status": "processing",
                "video_url": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

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
    job_id = request.path_params["job_id"]
    job = jobs_db.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)

    now = time.time()
    last_poll = last_poll_time.get(job_id, 0)

    if now - last_poll > POLL_CACHE_SECONDS and job["status"] != "completed":
        async with jobs_lock:
            if now - last_poll_time.get(job_id, 0) > POLL_CACHE_SECONDS:
                try:
                    status_data = await fetch_fal_job_status(job["endpoint_id"], job["request_id"])
                    status_obj = status_data["status"]
                    
                    if isinstance(status_obj, fal_client.Completed):
                        job["status"] = "completed"
                        result_data = await fetch_fal_job_result(job["endpoint_id"], job["request_id"])
                        job["video_url"] = result_data.get("video", {}).get("url")
                        job["width"] = result_data.get("video", {}).get("width")
                        job["height"] = result_data.get("video", {}).get("height")
                    elif isinstance(status_obj, fal_client.InProgress):
                        job["status"] = "processing"
                    elif isinstance(status_obj, fal_client.Queued):
                        job["status"] = "queued"
                    else:
                        job["status"] = str(status_obj).lower()
                    
                    last_poll_time[job_id] = now
                except fal_client.FalClientHTTPError as e:
                    logger.error(f"HTTP error from Fal.ai: {e.status_code} - {e.message}")
                    job["status"] = "failed"
                    job["error"] = f"Fal.ai API error: {e.status_code}"
                except fal_client.FalClientError as e:
                    logger.error(f"Failed to fetch job status from Fal.ai: {e}")
                    job["status"] = "failed"
                    job["error"] = f"FAL client error: {str(e)}"

    response_data = {
        "job_id": job["job_id"],
        "status": job["status"],
        "video_url": job.get("video_url"),
        "width": job.get("width"),
        "height": job.get("height"),
        "created_at": job["created_at"],
    }
    
    if job.get("error"):
        response_data["error"] = job["error"]
    
    return JSONResponse(response_data)


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
