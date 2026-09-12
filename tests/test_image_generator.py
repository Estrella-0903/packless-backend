import asyncio

from app.services import image_generator


def test_submit_returns_task_without_polling(monkeypatch) -> None:
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    monkeypatch.setattr(image_generator, "_normalized_data_url", lambda _: "data:image/jpeg;base64,AA==")
    monkeypatch.setattr(
        image_generator,
        "_submit_task",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("Submission must not block on Seedream generation")
        ),
    )
    result = asyncio.run(image_generator.generate_optimized_image(b"fixture", "prompt"))
    assert result["success"] and result["task_id"].startswith("seedream_")
    assert result["status"] == "PENDING"
    image_generator.IMAGE_TASK_CACHE.clear()


def test_submit_requires_seedream_key(monkeypatch) -> None:
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    result = asyncio.run(image_generator.submit_optimized_image_task(b"fixture", "prompt"))
    assert not result["success"]
    assert "ARK_API_KEY" in result["error"]


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
