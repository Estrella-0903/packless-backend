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


def test_submit_returns_task_without_polling(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(image_generator, "_normalized_data_url", lambda _: "data:image/jpeg;base64,AA==")
    monkeypatch.setattr(image_generator.ImageGeneration, "async_call", lambda **kwargs: _response("PENDING"))
    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("Submission must not fetch task status")
    monkeypatch.setattr(image_generator.ImageGeneration, "fetch", unexpected_fetch)
    result = asyncio.run(image_generator.generate_optimized_image(b"fixture", "prompt"))
    assert result["success"] and result["task_id"] == "task-test"
    assert result["status"] == "PENDING"
    image_generator.IMAGE_TASK_CACHE.clear()


def test_submit_timeout_is_clear(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    async def timeout(coroutine, **kwargs):
        coroutine.close()
        raise TimeoutError()
    monkeypatch.setattr(image_generator.asyncio, "wait_for", timeout)
    result = asyncio.run(image_generator.submit_optimized_image_task(b"fixture", "prompt"))
    assert not result["success"]
    assert "submission timed out" in result["error"]


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
