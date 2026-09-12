from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from http import HTTPStatus
from typing import Any

import dashscope
from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas.models import AnalysisData
from app.services.analysis_normalizer import normalize_analysis_result
from app.services.prompt_builder import build_analysis_messages


load_dotenv()

MODEL_NAME = os.getenv("DASHSCOPE_VISION_MODEL", "qwen3-vl-plus")
logger = logging.getLogger(__name__)


def _provider_failure(response: Any) -> "AIAnalyzerError":
    provider_code = str(getattr(response, "code", "") or "").strip()
    provider_message = str(getattr(response, "message", "") or "").strip()
    request_id = str(getattr(response, "request_id", "") or "").strip()
    logger.error(
        "[ANALYZE] DashScope rejected request: status=%s code=%s request_id=%s message=%s",
        getattr(response, "status_code", "unknown"),
        provider_code or "unknown",
        request_id or "unknown",
        provider_message or "unknown",
    )

    normalized_code = provider_code.lower()
    normalized_message = provider_message.lower()
    if normalized_code == "arrearage" or "overdue payment" in normalized_message:
        return AIAnalyzerError(
            "AI_BILLING_ERROR",
            "AI 分析服务账户余额或计费状态异常，请恢复 DashScope 服务后重试。",
        )
    if normalized_code in {"invalidapikey", "invalid_api_key", "unauthorized"}:
        return AIAnalyzerError(
            "AI_AUTH_ERROR",
            "AI 分析服务鉴权失败，请检查 DashScope API Key。",
        )
    if any(token in normalized_code for token in ("throttl", "ratelimit", "quota")):
        return AIAnalyzerError(
            "AI_RATE_LIMITED",
            "AI 分析服务当前请求过多，请稍后重试。",
        )
    return AIAnalyzerError(
        "AI_ANALYSIS_FAILED",
        "AI 包装分析服务调用失败，请稍后重试。",
    )


class AIAnalyzerError(RuntimeError):
    """A safe, user-facing failure from the AI analysis integration."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _image_data_url(image_bytes: bytes, content_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _extract_text(response: Any) -> str:
    try:
        content = response.output.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI packaging analysis returned an unexpected response.",
        ) from exc

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        text = "".join(text_parts)
        if text:
            return text
    raise AIAnalyzerError(
        "AI_ANALYSIS_FAILED",
        "AI packaging analysis returned no text result.",
    )


def _preview(value: Any, limit: int = 3000) -> str:
    text = str(value).replace("\x00", "").strip()
    return text if len(text) <= limit else f"{text[:limit]}... [truncated]"


def clean_model_output(text: str) -> str:
    """Remove wrappers and return the first complete JSON object in model text."""
    if not isinstance(text, str):
        return ""
    cleaned = text.lstrip("\ufeff").strip()
    cleaned = re.sub(r"```\s*json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("```", "").strip()

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        candidate = cleaned[match.start() :]
        try:
            value, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return candidate[:end].strip()
    first_brace = cleaned.find("{")
    if first_brace != -1:
        last_brace = cleaned.rfind("}")
        end = last_brace + 1 if last_brace >= first_brace else len(cleaned)
        return cleaned[first_brace:end].strip()
    return ""


def _parse_analysis(text: str, filename: str) -> AnalysisData:
    print(f"[ANALYZE] raw model output: {_preview(text)}", flush=True)
    cleaned = clean_model_output(text)
    print(f"[ANALYZE] cleaned model output: {_preview(cleaned)}", flush=True)
    if not cleaned:
        print("[ANALYZE] json parse fail: AI returned non-JSON text", flush=True)
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI returned non-JSON text.",
        )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"[ANALYZE] json parse fail: {_preview(exc)}", flush=True)
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "JSON parse failed.",
        ) from exc

    print("[ANALYZE] json parse success", flush=True)
    if not isinstance(payload, dict):
        print("[ANALYZE] schema normalize fail: Missing required root object", flush=True)
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "Missing required root object.",
        )

    try:
        normalized = normalize_analysis_result(payload, filename)
        result = AnalysisData.model_validate(normalized)
    except (TypeError, ValueError, ValidationError) as exc:
        print(f"[ANALYZE] schema normalize fail: {_preview(exc)}", flush=True)
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            f"JSON extracted but normalization failed: {_preview(exc, 300)}",
        ) from exc
    print("[ANALYZE] schema normalize success", flush=True)
    print(
        "[ANALYZE] final normalized result: "
        f"{_preview(json.dumps(normalized, ensure_ascii=False))}",
        flush=True,
    )
    return result


def _call_dashscope(
    image_bytes: bytes,
    content_type: str,
    filename: str,
    api_key: str,
) -> AnalysisData:
    messages = build_analysis_messages(_image_data_url(image_bytes, content_type))

    try:
        print("[ANALYZE] calling qwen vision model", flush=True)
        response = dashscope.MultiModalConversation.call(
            api_key=api_key,
            model=MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
            enable_thinking=False,
            result_format="message",
        )
    except Exception as exc:
        logger.exception("[ANALYZE] DashScope request raised an exception")
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI 包装分析服务连接失败，请稍后重试。",
        ) from exc

    if response.status_code != HTTPStatus.OK:
        raise _provider_failure(response)
    return _parse_analysis(_extract_text(response), filename)


async def analyze_image(
    image_bytes: bytes,
    content_type: str,
    filename: str,
) -> AnalysisData:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise AIAnalyzerError(
            "AI_CONFIGURATION_ERROR",
            "DASHSCOPE_API_KEY is not configured.",
        )
    if not image_bytes:
        raise AIAnalyzerError("EMPTY_IMAGE", "The uploaded image is empty.")

    return await asyncio.to_thread(
        _call_dashscope,
        image_bytes,
        content_type,
        filename,
        api_key,
    )
