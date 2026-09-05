from __future__ import annotations

import asyncio
import base64
import json
import os
from http import HTTPStatus
from typing import Any
from uuid import uuid4

import dashscope
from dotenv import load_dotenv
from pydantic import ValidationError

from app.schemas.models import AnalysisData
from app.services.prompt_builder import build_analysis_messages


load_dotenv()

MODEL_NAME = os.getenv("DASHSCOPE_VISION_MODEL", "qwen3-vl-plus")

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


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return cleaned.strip()


def _parse_analysis(text: str, filename: str) -> AnalysisData:
    try:
        payload = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as exc:
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI packaging analysis returned invalid JSON.",
        ) from exc

    if not isinstance(payload, dict):
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI packaging analysis returned an invalid data structure.",
        )

    payload["analysis_id"] = f"analysis_{uuid4().hex[:12]}"
    payload["filename"] = filename
    try:
        return AnalysisData.model_validate(payload)
    except ValidationError as exc:
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI packaging analysis did not match the required structure.",
        ) from exc


def _call_dashscope(
    image_bytes: bytes,
    content_type: str,
    filename: str,
    api_key: str,
) -> AnalysisData:
    messages = build_analysis_messages(_image_data_url(image_bytes, content_type))

    try:
        response = dashscope.MultiModalConversation.call(
            api_key=api_key,
            model=MODEL_NAME,
            messages=messages,
            response_format={"type": "json_object"},
            enable_thinking=False,
            result_format="message",
        )
    except Exception as exc:
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI packaging analysis failed.",
        ) from exc

    if response.status_code != HTTPStatus.OK:
        raise AIAnalyzerError(
            "AI_ANALYSIS_FAILED",
            "AI packaging analysis failed.",
        )
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
