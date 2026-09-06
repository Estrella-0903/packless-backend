import asyncio
import time

import httpx

from app.main import app
from app.services import image_generator as wan


def response(status, url=""):
    return {"status_code": 200, "output": {"task_id": "task-async-test", "task_status": status,
            "results": [{"url": url}] if url else []}}


def test_short_http_requests_and_single_download(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-key")
    monkeypatch.setattr(wan, "_normalized_data_url", lambda image: "data:image/jpeg;base64,test")
    monkeypatch.setattr(wan, "_submit_task", lambda *args: response("PENDING"))
    states = iter([response("RUNNING"), response("SUCCEEDED", "https://example.test/image?signature=private")])
    fetches = []
    def fetch(*args, **kwargs):
        fetches.append(1)
        return next(states)
    monkeypatch.setattr(wan.ImageGeneration, "fetch", fetch)

    async def scenario():
        wan.IMAGE_TASK_CACHE.clear()
        download_started = asyncio.Event()
        release_download = asyncio.Event()
        downloads = []
        async def download(url):
            downloads.append(url)
            download_started.set()
            await release_download.wait()
            return "/generated/test.png"
        monkeypatch.setattr(wan, "_download_result", download)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            started = time.monotonic()
            result = await client.post("/api/redesign", data={"analysis_result": '{}'}, files={"image": ("test.jpg", b"fixture", "image/jpeg")})
            assert time.monotonic() - started < 1
            plan = result.json()["data"]
            assert result.status_code == 200 and plan["image_task_id"] == "task-async-test"
            assert plan["image_generation_status"] == "PENDING"
            assert not plan["image_generation_failed"] and not fetches and not downloads
            url = "/api/redesign/image-status/task-async-test"
            assert (await client.get(url)).json()["data"]["status"] == "PENDING"
            await wan.IMAGE_TASK_CACHE["task-async-test"]["work"]
            assert (await client.get(url)).json()["data"]["status"] == "RUNNING"
            await asyncio.wait_for(download_started.wait(), 1)
            # Download deliberately cannot finish; all polling responses stay short.
            for _ in range(3):
                started = time.monotonic()
                reply = (await client.get(url)).json()
                assert time.monotonic() - started < 0.5
                assert reply["data"]["status"] == "RUNNING"
                assert "signature" not in str(reply)
            assert len(downloads) == 1 and len(fetches) == 2
            release_download.set()
            await wan.IMAGE_TASK_CACHE["task-async-test"]["work"]
            for _ in range(3):
                final = (await client.get(url)).json()["data"]
                assert final["status"] == "SUCCEEDED"
                assert final["optimized_image_url"] == "/generated/test.png"
            assert len(downloads) == 1 and len(fetches) == 2
        wan.IMAGE_TASK_CACHE.clear()
    asyncio.run(scenario())


def test_task_failure_redacts_key_and_url(monkeypatch, capsys):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret-test-key")
    def fail(*args, **kwargs):
        raise RuntimeError("secret-test-key https://example.test/?signature=hidden failed")
    monkeypatch.setattr(wan.ImageGeneration, "fetch", fail)
    async def scenario():
        wan.IMAGE_TASK_CACHE["failure"] = {"status": "PENDING", "created": time.monotonic(), "work": None}
        await wan.check_optimized_image_task("failure")
        await wan.IMAGE_TASK_CACHE["failure"]["work"]
        result = await wan.check_optimized_image_task("failure")
        assert result["status"] == "FAILED"
        assert "secret-test-key" not in str(result) and "signature" not in str(result)
        wan.IMAGE_TASK_CACHE.clear()
    asyncio.run(scenario())
    logs = capsys.readouterr().out
    assert "secret-test-key" not in logs and "signature" not in logs


def test_unknown_task_and_missing_key(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    async def scenario():
        assert (await wan.check_optimized_image_task("nonexistent"))["status"] == "FAILED"
        result = await wan.submit_optimized_image_task(b"fixture", "prompt")
        assert not result["success"] and "DASHSCOPE_API_KEY" in result["error"]
    asyncio.run(scenario())


def test_download_failure_is_terminal(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-only-key")
    monkeypatch.setattr(wan.ImageGeneration, "fetch", lambda *a, **k: response("SUCCEEDED", "https://example.test/image"))
    async def fail(url):
        raise wan.ImageGeneratorError("Generated image download failed.")
    monkeypatch.setattr(wan, "_download_result", fail)
    async def scenario():
        wan.IMAGE_TASK_CACHE["download-fail"] = {"status": "PENDING", "created": time.monotonic(), "work": None}
        await wan.check_optimized_image_task("download-fail")
        await wan.IMAGE_TASK_CACHE["download-fail"]["work"]
        result = await wan.check_optimized_image_task("download-fail")
        assert result["status"] == "FAILED" and not result["optimized_image_url"]
        wan.IMAGE_TASK_CACHE.clear()
    asyncio.run(scenario())
