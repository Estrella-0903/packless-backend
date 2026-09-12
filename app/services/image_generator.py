"""Seedream-backed image editing with the legacy local task interface."""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError


load_dotenv()

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

MODEL_NAME = os.getenv("SEEDREAM_IMAGE_MODEL", "doubao-seedream-5-0-pro-260628")
API_URL = os.getenv(
    "SEEDREAM_API_URL",
    "https://ark.cn-beijing.volces.com/api/v3/images/generations",
)
IMAGE_SIZE = os.getenv("SEEDREAM_IMAGE_SIZE", "2K")
BASE_DIR = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = BASE_DIR / "frontend" / "generated"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_DIMENSION = 240
MAX_DIMENSION = 8000
CONNECT_TIMEOUT_SECONDS = 10
GENERATION_READ_TIMEOUT_SECONDS = 180
GENERATION_DEADLINE_SECONDS = 210
MIN_VISUAL_CHANGE_SCORE = 0.6
MAX_VISUAL_RETRIES = 1


class ImageGeneratorError(RuntimeError):
    """A safe image-generation failure that never exposes provider credentials."""

    def __init__(
        self, message: str, raw_response: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response or {}


def _normalized_data_url(image_bytes: bytes) -> str:
    if not image_bytes:
        raise ImageGeneratorError("The uploaded image is empty.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImageGeneratorError("The uploaded image exceeds the 10 MB limit.")
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            width, height = source.size
            if not (
                MIN_DIMENSION <= width <= MAX_DIMENSION
                and MIN_DIMENSION <= height <= MAX_DIMENSION
            ):
                raise ImageGeneratorError(
                    "Image width and height must each be between 240 and 8000 pixels."
                )
            image = source.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageGeneratorError("The uploaded file is not a valid image.") from exc
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _safe_error(message: Any, api_key: str) -> str:
    text = str(message or "AI image generation failed.").strip()
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    text = re.sub(r"https?://\S+", "[provider URL redacted]", text)
    return text[:500]


def _loggable_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _submit_task(image_data_url: str, prompt: str, api_key: str) -> dict[str, Any]:
    """Call Seedream's synchronous endpoint from a worker thread."""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "image": image_data_url,
        "size": IMAGE_SIZE,
        "sequential_image_generation": "disabled",
        "stream": False,
        "response_format": "url",
        "watermark": False,
    }
    timeout = httpx.Timeout(
        GENERATION_READ_TIMEOUT_SECONDS,
        connect=CONNECT_TIMEOUT_SECONDS,
    )
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    return {"status_code": response.status_code, "body": body}


def _extract_result_url(response: dict[str, Any]) -> str:
    body = response.get("body") or {}
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    raise ImageGeneratorError("Seedream succeeded but returned no image URL.")


def _validate_provider_response(response: dict[str, Any]) -> None:
    if response.get("status_code") != 200:
        raise ImageGeneratorError("Seedream image generation was rejected by the provider.")


async def _download_result(provider_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            response = await client.get(provider_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ImageGeneratorError("Generated image download failed.") from exc
    return await asyncio.to_thread(_save_downloaded_image, response.content)


def _save_downloaded_image(content: bytes) -> str:
    if not content:
        raise ImageGeneratorError("Generated image download returned invalid content.")
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            generated_image = (
                source.copy()
                if source.mode in {"1", "L", "LA", "P", "RGB", "RGBA"}
                else source.convert("RGB")
            )
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageGeneratorError(
            "Generated image download returned invalid image bytes."
        ) from exc
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"redesign_{uuid4().hex}.png"
    destination = GENERATED_DIR / filename
    try:
        generated_image.save(destination, format="PNG", optimize=True)
    except OSError as exc:
        raise ImageGeneratorError("Generated image could not be saved locally.") from exc
    local_url = f"/generated/{filename}"
    logger.info(
        "Seedream image saved (path=%s, optimized_image_url=%s)",
        destination,
        local_url,
    )
    print(f"[SEEDREAM] local image saved=True, optimized_image_url={local_url}", flush=True)
    return local_url


IMAGE_TASK_CACHE: dict[str, dict[str, Any]] = {}
TASK_TTL_SECONDS = 3600
MAX_CACHED_TASKS = 1024


def _task_view(task_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": entry["status"],
        "optimized_image_url": entry.get("local_image_url", ""),
        "error": entry.get("error", ""),
        "visual_change_score": entry.get("visual_change_score"),
        "regeneration_attempted": bool(entry.get("retry_count", 0)),
    }


def _visual_change_score(reference_data_url: str, local_url: str) -> float | None:
    """Small aligned-image proxy: 0 is identical and 1 is clearly changed."""
    try:
        encoded = reference_data_url.split(",", 1)[1]
        reference_bytes = base64.b64decode(encoded, validate=True)
        filename = Path(urlsplit(local_url).path).name
        generated_path = GENERATED_DIR / filename
        with Image.open(io.BytesIO(reference_bytes)) as before_source, Image.open(generated_path) as after_source:
            before = before_source.convert("RGB").resize((96, 96), Image.Resampling.LANCZOS)
            after = after_source.convert("RGB").resize((96, 96), Image.Resampling.LANCZOS)
            differences = [abs(a - b) for a, b in zip(before.tobytes(), after.tobytes())]
        mean_difference = sum(differences) / len(differences)
        changed_ratio = sum(value >= 20 for value in differences) / len(differences)
        raw_score = mean_difference / 45 * .7 + changed_ratio * .3
        return round(min(1, raw_score * 1.4), 3)
    except (OSError, ValueError, IndexError):
        return None


def _remove_generated_file(local_url: str) -> None:
    filename = Path(urlsplit(local_url).path).name
    target = (GENERATED_DIR / filename).resolve()
    if target.parent == GENERATED_DIR.resolve() and target.exists():
        target.unlink()


def _retry_prompt(prompt: str) -> str:
    return prompt + """

REGENERATION REQUIREMENT: the previous result was too visually similar to the reference.
Make the already-approved structural changes substantially clearer. The outer package must be visibly smaller, the layout visibly more compact, and every approved removed or merged layer must be absent as a separate piece. Preserve the same product, brand, camera angle, background and lighting. Do not solve this by recoloring or changing the whole scene."""


def _api_key() -> str:
    return os.getenv("ARK_API_KEY", "")


async def generate_optimized_image(image_bytes: bytes, prompt: str) -> dict[str, Any]:
    """Compatibility entry point: create a task without blocking for Seedream."""
    return await submit_optimized_image_task(image_bytes, prompt)


async def submit_optimized_image_task(image_bytes: bytes, prompt: str) -> dict[str, Any]:
    """Keep the existing submit/poll contract over Seedream's synchronous API."""
    api_key = _api_key()
    started = time.monotonic()
    print("[SEEDREAM SUBMIT] start", flush=True)
    try:
        if not api_key:
            raise ImageGeneratorError("ARK_API_KEY is not configured.")
        for key, entry in list(IMAGE_TASK_CACHE.items()):
            work = entry.get("work")
            if time.monotonic() - entry["created"] > TASK_TTL_SECONDS and (
                work is None or work.done()
            ):
                IMAGE_TASK_CACHE.pop(key, None)
        if len(IMAGE_TASK_CACHE) >= MAX_CACHED_TASKS:
            raise ImageGeneratorError("Image task capacity reached. Please try later.")

        data_url = await asyncio.to_thread(_normalized_data_url, image_bytes)
        task_id = f"seedream_{uuid4().hex[:24]}"
        IMAGE_TASK_CACHE[task_id] = {
            "status": "PENDING",
            "created": time.monotonic(),
            "local_image_url": "",
            "error": "",
            "work": None,
            "reference_data_url": data_url,
            "prompt": prompt,
            "retry_count": 0,
            "visual_change_score": None,
        }
        print(
            f"[SEEDREAM SUBMIT] success task_id={task_id} "
            f"model={MODEL_NAME} elapsed={time.monotonic() - started:.1f}s",
            flush=True,
        )
        return {"success": True, "task_id": task_id, "status": "PENDING"}
    except Exception as exc:
        error = (
            str(exc)
            if isinstance(exc, ImageGeneratorError)
            else "AI image task submission failed. Please try again."
        )
        print(
            f"[SEEDREAM SUBMIT] failed elapsed={time.monotonic() - started:.1f}s "
            f"detail={_safe_error(exc, api_key)}",
            flush=True,
        )
        return {"success": False, "task_id": "", "status": "FAILED", "error": error}


async def finalize_optimized_image(task_id: str) -> dict[str, Any]:
    entry = IMAGE_TASK_CACHE[task_id]
    lock = entry.setdefault("download_lock", asyncio.Lock())
    async with lock:
        if entry["status"] == "SUCCEEDED":
            return _task_view(task_id, entry)
        while True:
            local_url = await asyncio.wait_for(
                _download_result(entry["provider_url"]), timeout=95
            )
            score = _visual_change_score(entry.get("reference_data_url", ""), local_url)
            entry["visual_change_score"] = score
            print(f"[SEEDREAM VISUAL] task_id={task_id} score={score}", flush=True)
            if score is not None and score < MIN_VISUAL_CHANGE_SCORE:
                if entry.get("retry_count", 0) >= MAX_VISUAL_RETRIES:
                    _remove_generated_file(local_url)
                    raise ImageGeneratorError(
                        "Generated image did not meet the minimum visible-change threshold."
                    )
                _remove_generated_file(local_url)
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        _submit_task,
                        entry["reference_data_url"],
                        _retry_prompt(entry["prompt"]),
                        _api_key(),
                    ),
                    timeout=GENERATION_DEADLINE_SECONDS,
                )
                _validate_provider_response(response)
                entry.update(
                    provider_url=_extract_result_url(response),
                    retry_count=entry.get("retry_count", 0) + 1,
                )
                continue
            entry.update(status="SUCCEEDED", local_image_url=local_url, error="")
            for key in ("provider_url", "reference_data_url", "prompt"):
                entry.pop(key, None)
            print(f"[SEEDREAM DONE] task_id={task_id} local_url={local_url}", flush=True)
            return _task_view(task_id, entry)


async def _refresh_image_task(task_id: str) -> None:
    entry = IMAGE_TASK_CACHE[task_id]
    api_key = _api_key()
    response: dict[str, Any] | None = None
    try:
        if not api_key:
            raise ImageGeneratorError("ARK_API_KEY is not configured.")
        entry["status"] = "RUNNING"
        response = await asyncio.wait_for(
            asyncio.to_thread(
                _submit_task,
                entry["reference_data_url"],
                entry["prompt"],
                api_key,
            ),
            timeout=GENERATION_DEADLINE_SECONDS,
        )
        _validate_provider_response(response)
        entry["provider_url"] = _extract_result_url(response)
        print(
            f"[SEEDREAM RESULT] task_id={task_id} "
            f"url={_loggable_url(entry['provider_url'])}",
            flush=True,
        )
        await finalize_optimized_image(task_id)
    except Exception as exc:
        timed_out = isinstance(exc, (TimeoutError, httpx.TimeoutException))
        error = (
            "Seedream image generation or download timed out. Please regenerate."
            if timed_out
            else _safe_error(exc, api_key)
        )
        entry.update(status="FAILED", error=error, local_image_url="")
        entry.pop("provider_url", None)
        print(
            f"[SEEDREAM STATUS] task_id={task_id} status=FAILED "
            f"error={_safe_error(error, api_key)}",
            flush=True,
        )


async def check_optimized_image_task(task_id: str) -> dict[str, Any]:
    entry = IMAGE_TASK_CACHE.get(task_id)
    if entry is None:
        return {
            "task_id": task_id,
            "status": "FAILED",
            "optimized_image_url": "",
            "error": "Image task not found or expired after server restart. Please regenerate.",
        }
    work = entry.get("work")
    if entry["status"] not in {"SUCCEEDED", "FAILED"} and (
        work is None or work.done()
    ):
        entry["work"] = asyncio.create_task(_refresh_image_task(task_id))
    return _task_view(task_id, entry)
