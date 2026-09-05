import asyncio
from types import SimpleNamespace

from app.services import image_generator


def _response(status: str, *, image_url: str = "") -> SimpleNamespace:
    content = [{"image": image_url}] if image_url else []
    return SimpleNamespace(
        status_code=200,
        request_id="request-test",
        code=None,
        message=None,
        output=SimpleNamespace(
            task_id="task-test",
            task_status=status,
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        ),
    )


def test_async_wan_task_is_polled_until_success(monkeypatch, caplog) -> None:
    states = iter(
        [
            _response("RUNNING"),
            _response("SUCCEEDED", image_url="https://example.test/result.png?token=x"),
        ]
    )
    monkeypatch.setattr(
        image_generator.ImageGeneration,
        "async_call",
        lambda **kwargs: _response("PENDING"),
    )
    monkeypatch.setattr(
        image_generator.ImageGeneration,
        "fetch",
        lambda task_id, api_key=None: next(states),
    )

    async def no_wait(seconds: float) -> None:
        assert seconds == image_generator.POLL_INTERVAL_SECONDS

    monkeypatch.setattr(image_generator.asyncio, "sleep", no_wait)
    caplog.set_level("INFO")
    image_url, raw = asyncio.run(
        image_generator._submit_and_poll("data:image/jpeg;base64,AA==", "prompt", "key")
    )
    assert image_url.startswith("https://example.test/result.png")
    assert raw["output"]["task_status"] == "SUCCEEDED"
    assert "task_id=task-test" in caplog.text
    assert "status=PENDING" in caplog.text
    assert "status=RUNNING" in caplog.text
    assert "status=SUCCEEDED" in caplog.text
    assert "?token=x" not in caplog.text


def test_async_wan_task_timeout_is_clear(monkeypatch) -> None:
    monkeypatch.setattr(image_generator, "MAX_POLL_ATTEMPTS", 2)
    monkeypatch.setattr(
        image_generator.ImageGeneration,
        "async_call",
        lambda **kwargs: _response("PENDING"),
    )
    monkeypatch.setattr(
        image_generator.ImageGeneration,
        "fetch",
        lambda task_id, api_key=None: _response("RUNNING"),
    )

    async def no_wait(seconds: float) -> None:
        return None

    monkeypatch.setattr(image_generator.asyncio, "sleep", no_wait)
    try:
        asyncio.run(
            image_generator._submit_and_poll(
                "data:image/jpeg;base64,AA==", "prompt", "key"
            )
        )
    except image_generator.ImageGeneratorError as exc:
        assert "timed out after 2 polls" in str(exc)
    else:
        raise AssertionError("Expected timeout")


def test_prompt_requires_visual_alignment() -> None:
    prompt = __import__(
        "app.services.prompt_builder", fromlist=["build_image_generation_prompt"]
    ).build_image_generation_prompt(
        {"product": {"category": "cosmetics", "product_name": "Cream"}},
        {
            "remove_plastic_film": True,
            "replace_inner_tray": {"from": "PET", "to": "Molded pulp"},
            "resize_outer_box": "15-25%",
        },
    )
    for requirement in (
        "camera angle",
        "product position",
        "composition",
        "background",
        "lighting direction",
        "brand colors",
        "before/after comparison slider",
    ):
        assert requirement in prompt
