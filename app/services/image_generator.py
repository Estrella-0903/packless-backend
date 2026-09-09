from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from requests.exceptions import ConnectTimeout, ReadTimeout, Timeout as RequestsTimeout
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
SUBMIT_CONNECT_TIMEOUT_SECONDS = 10
SUBMIT_READ_TIMEOUT_SECONDS = 30
SUBMIT_DEADLINE_SECONDS = 45
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
    text = re.sub(r"https?://\S+", "[provider URL redacted]", text)
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
    print("[WAN] submitting task", flush=True)
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
        # Installed SDK passes request_timeout unchanged to requests.Session.post.
        request_timeout=(SUBMIT_CONNECT_TIMEOUT_SECONDS, SUBMIT_READ_TIMEOUT_SECONDS),
    )


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
        "Wan image generation: downloaded and saved (path=%s, optimized_image_url=%s)",
        destination,
        local_url,
    )
    print(
        f"[WAN] local image saved=True, optimized_image_url={local_url}",
        flush=True,
    )
    return local_url


async def generate_optimized_image(image_bytes: bytes, prompt: str) -> dict[str, Any]:
    """Compatibility entry point: submit only, never await image completion."""
    return await submit_optimized_image_task(image_bytes, prompt)


# MVP in-memory task cache. Single process/worker only; restart loses tasks.
# Internal provider URLs and task objects are NEVER serialized to API clients.
IMAGE_TASK_CACHE: dict[str, dict[str, Any]] = {}
TASK_TTL_SECONDS = 3600
MAX_CACHED_TASKS = 1024


def _task_view(task_id: str, entry: dict) -> dict:
    return {"task_id": task_id, "status": entry["status"],
            "optimized_image_url": entry.get("local_image_url", ""),
            "error": entry.get("error", ""),
            "visual_change_score": entry.get("visual_change_score"),
            "regeneration_attempted": bool(entry.get("retry_count", 0))}


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
            differences = [abs(a-b) for a, b in zip(before.tobytes(), after.tobytes())]
        mean_difference = sum(differences) / len(differences)
        changed_ratio = sum(value >= 20 for value in differences) / len(differences)
        raw_score = mean_difference / 45 * .7 + changed_ratio * .3
        # A 40% sensitivity calibration reflects that an aligned package edit
        # intentionally preserves most pixels (brand, product and background).
        # Identical images still score 0; subtle restyles remain far below 0.6.
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


async def submit_optimized_image_task(image_bytes: bytes, prompt: str) -> dict:
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    started = time.monotonic()
    print("[WAN SUBMIT] start attempt=1", flush=True)
    print(f"[WAN] model={MODEL_NAME}, key configured={bool(api_key)}", flush=True)
    try:
        if not api_key:
            raise ImageGeneratorError("DASHSCOPE_API_KEY is not configured.")
        for key, entry in list(IMAGE_TASK_CACHE.items()):
            work = entry.get("work")
            if time.monotonic() - entry["created"] > TASK_TTL_SECONDS and (work is None or work.done()):
                IMAGE_TASK_CACHE.pop(key, None)
        if len(IMAGE_TASK_CACHE) >= MAX_CACHED_TASKS:
            raise ImageGeneratorError("Image task capacity reached. Please try later.")
        async def submit():
            data_url = await asyncio.to_thread(_normalized_data_url, image_bytes)
            response = await asyncio.to_thread(_submit_task, data_url, prompt, api_key)
            return response, data_url
        # Bounds the HTTP wait; never polls or downloads on this request.
        response, data_url = await asyncio.wait_for(submit(), timeout=SUBMIT_DEADLINE_SECONDS)
        if _value(response, "status_code") != HTTPStatus.OK:
            print(f"[WAN SUBMIT] provider_error status_code={_value(response, 'status_code')} "
                  f"elapsed={time.monotonic()-started:.1f}s detail="
                  f"{_safe_error(_value(response, 'message') or _value(response, 'code'), api_key)}", flush=True)
            raise ImageGeneratorError("AI image task submission was rejected by the provider.")
        task_id = str(_output_value(response, "task_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise ImageGeneratorError("Wan task submission returned no valid task_id.")
        IMAGE_TASK_CACHE[task_id] = {"status": "PENDING", "created": time.monotonic(),
                                    "local_image_url": "", "error": "", "work": None,
                                    "provider_task_id": task_id, "reference_data_url": data_url,
                                    "prompt": prompt, "retry_count": 0,
                                    "visual_change_score": None}
        print(f"[WAN] submitted task_id={task_id}", flush=True)
        print(f"[WAN SUBMIT] success task_id={task_id} elapsed={time.monotonic()-started:.1f}s", flush=True)
        return {"success": True, "task_id": task_id, "status": "PENDING"}
    except Exception as exc:
        timeout = isinstance(exc, (TimeoutError, RequestsTimeout))
        kind = "connect_timeout" if isinstance(exc, ConnectTimeout) else "read_timeout" if isinstance(exc, ReadTimeout) else "deadline_timeout" if isinstance(exc, TimeoutError) else "request_error"
        error = "AI image task submission timed out." if timeout else str(exc) if isinstance(exc, ImageGeneratorError) else "AI image task submission failed. Please try again."
        print(f"[WAN SUBMIT] {'timeout' if timeout else 'failed'} kind={kind} "
              f"elapsed={time.monotonic()-started:.1f}s detail={_safe_error(exc, api_key)}", flush=True)
        # Never replay an ambiguous POST: a read/deadline timeout can hide success.
        return {"success": False, "task_id": "", "status": "FAILED", "error": error}


async def finalize_optimized_image(task_id: str) -> dict:
    entry = IMAGE_TASK_CACHE[task_id]
    # Lock prevents concurrent status requests from downloading the same result.
    lock = entry.setdefault("download_lock", asyncio.Lock())
    async with lock:
        if entry["status"] == "SUCCEEDED":
            return _task_view(task_id, entry)
        entry["status"] = "RUNNING"
        local_url = await asyncio.wait_for(_download_result(entry["provider_url"]), timeout=35)
        score = _visual_change_score(entry.get("reference_data_url", ""), local_url)
        entry["visual_change_score"] = score
        print(f"[WAN VISUAL] task_id={task_id} score={score}", flush=True)
        if score is not None and score < MIN_VISUAL_CHANGE_SCORE:
            if entry.get("retry_count", 0) < MAX_VISUAL_RETRIES:
                _remove_generated_file(local_url)
                api_key = os.getenv("DASHSCOPE_API_KEY", "")
                retry_response = await asyncio.wait_for(
                    asyncio.to_thread(
                        _submit_task,
                        entry["reference_data_url"],
                        _retry_prompt(entry["prompt"]),
                        api_key,
                    ),
                    timeout=SUBMIT_DEADLINE_SECONDS,
                )
                if _value(retry_response, "status_code") != HTTPStatus.OK:
                    raise ImageGeneratorError("AI image regeneration was rejected by the provider.")
                retry_task_id = str(_output_value(retry_response, "task_id") or "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", retry_task_id):
                    raise ImageGeneratorError("AI image regeneration returned no valid task_id.")
                entry.update(status="PENDING", provider_task_id=retry_task_id,
                             retry_count=entry.get("retry_count", 0) + 1,
                             provider_url="", local_image_url="")
                print(f"[WAN VISUAL] retry submitted public_task_id={task_id} attempt=1", flush=True)
                return _task_view(task_id, entry)
            _remove_generated_file(local_url)
            raise ImageGeneratorError("Generated image did not meet the minimum visible-change threshold.")
        entry.update(status="SUCCEEDED", local_image_url=local_url, error="")
        for key in ("provider_url", "reference_data_url", "prompt"):
            entry.pop(key, None)
        print(f"[WAN DOWNLOAD] task_id={task_id} local_url={local_url}", flush=True)
        return _task_view(task_id, entry)


async def _refresh_image_task(task_id: str) -> None:
    entry = IMAGE_TASK_CACHE[task_id]
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    try:
        if not api_key:
            raise ImageGeneratorError("DASHSCOPE_API_KEY is not configured.")
        # Fetch is synchronous in the installed SDK. Run outside the event loop;
        # status HTTP requests return cached state while this operation is pending.
        provider_task_id = entry.get("provider_task_id", task_id)
        response = await asyncio.wait_for(asyncio.to_thread(ImageGeneration.fetch, provider_task_id, api_key=api_key), timeout=8)
        if _value(response, "status_code") != HTTPStatus.OK:
            raise ImageGeneratorError(_safe_error(_value(response, "message") or _value(response, "code"), api_key))
        status = str(_output_value(response, "task_status", "UNKNOWN")).upper()
        print(f"[WAN STATUS] task_id={task_id} status={status}", flush=True)
        if status == "SUCCEEDED":
            entry["provider_url"] = _extract_result_url(response)
            await finalize_optimized_image(task_id)
        elif status in {"PENDING", "RUNNING"}:
            entry["status"] = status
        else:
            raise ImageGeneratorError(_value(response, "message") or f"Wan task ended with status {status}.")
    except Exception as exc:
        error = "Image status query or download timed out. Please regenerate." if isinstance(exc, TimeoutError) else _safe_error(exc, api_key)
        entry.update(status="FAILED", error=error)
        entry.pop("provider_url", None)
        print(f"[WAN STATUS] task_id={task_id} status=FAILED error={error}", flush=True)


async def check_optimized_image_task(task_id: str) -> dict:
    entry = IMAGE_TASK_CACHE.get(task_id)
    if entry is None:
        return {"task_id": task_id, "status": "FAILED", "optimized_image_url": "",
                "error": "Image task not found or expired after server restart. Please regenerate."}
    work = entry.get("work")
    if entry["status"] not in {"SUCCEEDED", "FAILED"} and (work is None or work.done()):
        entry["work"] = asyncio.create_task(_refresh_image_task(task_id))
    return _task_view(task_id, entry)
