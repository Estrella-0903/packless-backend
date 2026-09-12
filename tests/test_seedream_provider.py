import asyncio
import time

import httpx
import pytest

from app.services import image_generator as seedream


@pytest.fixture(autouse=True)
def isolated_tasks(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-secret-key")
    monkeypatch.setattr(
        seedream, "_normalized_data_url", lambda _: "data:image/jpeg;base64,AA=="
    )
    seedream.IMAGE_TASK_CACHE.clear()
    yield
    seedream.IMAGE_TASK_CACHE.clear()


def provider_response(url="https://provider.test/result.png?signature=private"):
    return {"status_code": 200, "body": {"data": [{"url": url}]}}


def test_seedream_request_uses_ark_contract(monkeypatch):
    seen = {}

    def post(client, url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(
            200,
            json={"data": [{"url": "https://provider.test/result.png"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    result = seedream._submit_task(
        "data:image/jpeg;base64,AA==", "edit this package", "test-secret-key"
    )
    assert result["status_code"] == 200
    assert seen["url"] == "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    assert seen["headers"]["Authorization"] == "Bearer test-secret-key"
    assert seen["json"] == {
        "model": "doubao-seedream-5-0-pro-260628",
        "prompt": "edit this package",
        "image": "data:image/jpeg;base64,AA==",
        "size": "2K",
        "sequential_image_generation": "disabled",
        "stream": False,
        "response_format": "url",
        "watermark": False,
    }


def test_submit_stays_fast_and_provider_runs_on_status_poll(monkeypatch):
    calls = []

    def generate(*args):
        time.sleep(.1)
        calls.append(1)
        return provider_response()

    monkeypatch.setattr(seedream, "_submit_task", generate)
    monkeypatch.setattr(
        seedream,
        "_download_result",
        lambda _: asyncio.sleep(0, result="/generated/result.png"),
    )
    monkeypatch.setattr(seedream, "_visual_change_score", lambda *_: .8)

    async def scenario():
        started = time.monotonic()
        submitted = await seedream.submit_optimized_image_task(b"fixture", "prompt")
        assert time.monotonic() - started < .1
        assert submitted["status"] == "PENDING" and not calls
        await seedream.check_optimized_image_task(submitted["task_id"])
        await seedream.IMAGE_TASK_CACHE[submitted["task_id"]]["work"]
        final = await seedream.check_optimized_image_task(submitted["task_id"])
        assert final["status"] == "SUCCEEDED"
        assert final["optimized_image_url"] == "/generated/result.png"
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reply,error",
    [
        ({"status_code": 200, "body": {"data": []}}, "no image URL"),
        (
            {"status_code": 503, "body": {"error": {"message": "private detail"}}},
            "rejected by the provider",
        ),
    ],
)
def test_provider_failures_become_terminal_task_errors(monkeypatch, reply, error):
    monkeypatch.setattr(seedream, "_submit_task", lambda *args: reply)

    async def scenario():
        submitted = await seedream.submit_optimized_image_task(b"fixture", "prompt")
        await seedream.check_optimized_image_task(submitted["task_id"])
        await seedream.IMAGE_TASK_CACHE[submitted["task_id"]]["work"]
        final = await seedream.check_optimized_image_task(submitted["task_id"])
        assert final["status"] == "FAILED"
        assert error in final["error"]
        assert not final["optimized_image_url"]

    asyncio.run(scenario())


def test_provider_timeout_is_sanitized(monkeypatch):
    def timeout(*args):
        raise httpx.ReadTimeout(
            "test-secret-key https://provider.test/?signature=hidden timed out"
        )

    monkeypatch.setattr(seedream, "_submit_task", timeout)

    async def scenario():
        submitted = await seedream.submit_optimized_image_task(b"fixture", "prompt")
        await seedream.check_optimized_image_task(submitted["task_id"])
        await seedream.IMAGE_TASK_CACHE[submitted["task_id"]]["work"]
        final = await seedream.check_optimized_image_task(submitted["task_id"])
        assert final["status"] == "FAILED"
        assert "timed out" in final["error"]
        assert "test-secret-key" not in str(final)
        assert "signature" not in str(final)

    asyncio.run(scenario())
