from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from dashscope.aigc.image_generation import ImageGeneration
from dashscope.api_entities.dashscope_response import Message
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError


load_dotenv()

logger = logging.getLogger(__name__)
# httpx logs full signed OSS query strings at INFO; keep those temporary
# credentials out of application logs and emit our query-stripped URL instead.
logging.getLogger("httpx").setLevel(logging.WARNING)
MODEL_NAME = os.getenv("DASHSCOPE_IMAGE_MODEL", "wan2.6-image")
BASE_DIR = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = BASE_DIR / "frontend" / "generated"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIN_DIMENSION = 240
MAX_DIMENSION = 8000
POLL_INTERVAL_SECONDS = 2.5
MAX_POLL_ATTEMPTS = 10
TERMINAL_FAILURE_STATES = {"FAILED", "CANCELED", "UNKNOWN"}


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


def _value(container: Any, key: str, default: Any = None) -> Any:
    if isinstance(container, dict):
        return container.get(key, default)
    return getattr(container, key, default)


def _output_value(response: Any, key: str, default: Any = None) -> Any:
    return _value(_value(response, "output", {}), key, default)


def _safe_raw_response(response: Any) -> dict[str, Any]:
    output = _value(response, "output", {})
    if hasattr(output, "to_dict"):
        output = output.to_dict()
    elif not isinstance(output, dict):
        try:
            output = dict(output)
        except (TypeError, ValueError):
            output = {"task_status": _value(output, "task_status")}
    return {
        "status_code": _value(response, "status_code"),
        "request_id": _value(response, "request_id"),
        "code": _value(response, "code"),
        "message": _value(response, "message"),
        "output": output,
    }


def _safe_error(message: Any, api_key: str) -> str:
    text = str(message or "AI image generation failed.").strip()
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    return text[:500]


def _loggable_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _extract_result_url(response: Any) -> str:
    choices = _output_value(response, "choices", [])
    if choices:
        try:
            message_content = _value(_value(choices[0], "message", {}), "content", [])
        except (IndexError, TypeError):
            message_content = []
        for item in message_content or []:
            image_url = _value(item, "image")
            if image_url:
                return str(image_url)

    for item in _output_value(response, "results", []) or []:
        image_url = _value(item, "url") or _value(item, "image")
        if image_url:
            return str(image_url)
    output_image_url = _output_value(response, "output_image_url")
    if output_image_url:
        return str(output_image_url)
    raise ImageGeneratorError("Image generation succeeded but returned no image URL.")


def _submit_task(image_data_url: str, prompt: str, api_key: str) -> Any:
    logger.info("Wan image generation: submitting asynchronous task (model=%s)", MODEL_NAME)
    message = Message(
        role="user",
        content=[{"text": prompt}, {"image": image_data_url}],
    )
    return ImageGeneration.async_call(
        model=MODEL_NAME,
        api_key=api_key,
        messages=[message],
        negative_prompt=(
            "different product, changed logo, changed brand colors, changed camera angle, "
            "changed composition, changed background, changed lighting, dieline, engineering "
            "drawing, blueprint, exploded view, wireframe, infographic, illegible branding"
        ),
        prompt_extend=True,
        watermark=False,
        n=1,
        enable_interleave=False,
        size="1K",
    )


async def _submit_and_poll(
    image_data_url: str, prompt: str, api_key: str
) -> tuple[str, dict[str, Any]]:
    try:
        response = await asyncio.to_thread(
            _submit_task, image_data_url, prompt, api_key
        )
    except Exception as exc:
        raise ImageGeneratorError(_safe_error(exc, api_key)) from exc

    raw_response = _safe_raw_response(response)
    if _value(response, "status_code") != HTTPStatus.OK:
        error = _safe_error(
            _value(response, "message") or _value(response, "code"), api_key
        )
        logger.error("Wan image generation: task submission failed (%s)", error)
        raise ImageGeneratorError(error, raw_response)

    task_id = _output_value(response, "task_id")
    if not task_id:
        raise ImageGeneratorError(
            "Wan task submission returned no task_id.", raw_response
        )
    logger.info("Wan image generation: task submitted (task_id=%s)", task_id)

    current = response
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        status = str(_output_value(current, "task_status", "UNKNOWN")).upper()
        logger.info(
            "Wan image generation: task_id=%s status=%s poll=%d/%d",
            task_id,
            status,
            attempt,
            MAX_POLL_ATTEMPTS,
        )
        if status == "SUCCEEDED":
            provider_url = _extract_result_url(current)
            logger.info(
                "Wan image generation: task succeeded (task_id=%s, image_url=%s)",
                task_id,
                _loggable_url(provider_url),
            )
            return provider_url, _safe_raw_response(current)
        if status in TERMINAL_FAILURE_STATES:
            error = _safe_error(
                _value(current, "message")
                or _value(current, "code")
                or f"Wan task ended with status {status}.",
                api_key,
            )
            raise ImageGeneratorError(error, _safe_raw_response(current))

        if attempt == MAX_POLL_ATTEMPTS:
            break

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            current = await asyncio.to_thread(
                ImageGeneration.fetch, task_id, api_key=api_key
            )
        except Exception as exc:
            raise ImageGeneratorError(_safe_error(exc, api_key)) from exc
        if _value(current, "status_code") != HTTPStatus.OK:
            error = _safe_error(
                _value(current, "message") or _value(current, "code"), api_key
            )
            raise ImageGeneratorError(error, _safe_raw_response(current))

    logger.error("Wan image generation: polling timed out (task_id=%s)", task_id)
    raise ImageGeneratorError(
        f"Wan image generation timed out after {MAX_POLL_ATTEMPTS} polls.",
        _safe_raw_response(current),
    )


async def _download_result(provider_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            response = await client.get(provider_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ImageGeneratorError("Generated image download failed.") from exc

    if not response.content:
        raise ImageGeneratorError("Generated image download returned invalid content.")

    try:
        with Image.open(io.BytesIO(response.content)) as source:
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
        "Wan image generation: downloaded and saved (path=%s, optimized_image_url=%s)",
        destination,
        local_url,
    )
    return local_url


async def generate_optimized_image(
    image_bytes: bytes, prompt: str
) -> dict[str, Any]:
    """Create, poll, download, and expose one Wan-optimized package image."""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        error = "DASHSCOPE_API_KEY is not configured."
        logger.error("Wan image generation: %s", error)
        return {"success": False, "image_url": "", "raw_response": {}, "error": error}

    raw_response: dict[str, Any] = {}
    try:
        image_data_url = await asyncio.to_thread(_normalized_data_url, image_bytes)
        provider_url, raw_response = await _submit_and_poll(
            image_data_url, prompt, api_key
        )
        local_url = await _download_result(provider_url)
        logger.info("Wan image generation: returning optimized_image_url=%s", local_url)
        return {
            "success": True,
            "image_url": local_url,
            "raw_response": raw_response,
            "error": "",
        }
    except Exception as exc:
        error = _safe_error(exc, api_key)
        if isinstance(exc, ImageGeneratorError):
            raw_response = exc.raw_response
        logger.error("Wan image generation failed: %s", error)
        return {
            "success": False,
            "image_url": "",
            "raw_response": raw_response,
            "error": error,
        }
