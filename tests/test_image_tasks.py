import asyncio
import time

import httpx

from app.main import app
from app.services import image_generator as seedream


def response(url="https://example.test/image?signature=private"):
    return {"status_code": 200, "body": {"data": [{"url": url}]}}


def test_short_http_requests_and_single_download(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-only-key")
    monkeypatch.setattr(seedream, "_normalized_data_url", lambda image: "data:image/jpeg;base64,test")
    generations = []
    def generate(*args):
        generations.append(1)
        return response()
    monkeypatch.setattr(seedream, "_submit_task", generate)

    async def scenario():
        seedream.IMAGE_TASK_CACHE.clear()
        download_started = asyncio.Event()
        release_download = asyncio.Event()
        downloads = []
        async def download(url):
            downloads.append(url)
            download_started.set()
            await release_download.wait()
            return "/generated/test.png"
        monkeypatch.setattr(seedream, "_download_result", download)
        monkeypatch.setattr(seedream, "_visual_change_score", lambda *_: .8)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            started = time.monotonic()
            result = await client.post("/api/redesign", data={"analysis_result": '{}'}, files={"image": ("test.jpg", b"fixture", "image/jpeg")})
            assert time.monotonic() - started < 1
            payload = result.json()
            assert payload["success"] is True
            plan = payload["data"]
            task_id = plan["image_task_id"]
            assert result.status_code == 200 and task_id.startswith("seedream_")
            assert plan["image_generation_status"] == "PENDING"
            assert plan["optimized_image_url"] == ""
            assert plan["image_generation_failed"] is False
            assert plan["image_generation_error"] == ""
            assert not plan["image_generation_failed"] and not generations and not downloads
            url = f"/api/redesign/image-status/{task_id}"
            assert (await client.get(url)).json()["data"]["status"] == "PENDING"
            await asyncio.wait_for(download_started.wait(), 1)
            # Download deliberately cannot finish; all polling responses stay short.
            for _ in range(3):
                started = time.monotonic()
                reply = (await client.get(url)).json()
                assert time.monotonic() - started < 0.5
                assert reply["data"]["status"] == "RUNNING"
                assert "signature" not in str(reply)
            assert len(downloads) == 1 and len(generations) == 1
            release_download.set()
            await seedream.IMAGE_TASK_CACHE[task_id]["work"]
            for _ in range(3):
                final = (await client.get(url)).json()["data"]
                assert final["status"] == "SUCCEEDED"
                assert final["optimized_image_url"] == "/generated/test.png"
            assert len(downloads) == 1 and len(generations) == 1
        seedream.IMAGE_TASK_CACHE.clear()
    asyncio.run(scenario())


def test_task_failure_redacts_key_and_url(monkeypatch, capsys):
    monkeypatch.setenv("ARK_API_KEY", "secret-test-key")
    def fail(*args, **kwargs):
        raise RuntimeError("secret-test-key https://example.test/?signature=hidden failed")
    monkeypatch.setattr(seedream, "_submit_task", fail)
    async def scenario():
        seedream.IMAGE_TASK_CACHE["failure"] = {
            "status": "PENDING", "created": time.monotonic(), "work": None,
            "reference_data_url": "data:image/jpeg;base64,test", "prompt": "prompt",
        }
        await seedream.check_optimized_image_task("failure")
        await seedream.IMAGE_TASK_CACHE["failure"]["work"]
        result = await seedream.check_optimized_image_task("failure")
        assert result["status"] == "FAILED"
        assert "secret-test-key" not in str(result) and "signature" not in str(result)
        seedream.IMAGE_TASK_CACHE.clear()
    asyncio.run(scenario())
    logs = capsys.readouterr().out
    assert "secret-test-key" not in logs and "signature" not in logs


def test_unknown_task_and_missing_key(monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    async def scenario():
        assert (await seedream.check_optimized_image_task("nonexistent"))["status"] == "FAILED"
        result = await seedream.submit_optimized_image_task(b"fixture", "prompt")
        assert not result["success"] and "ARK_API_KEY" in result["error"]
    asyncio.run(scenario())


def test_download_failure_is_terminal(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "test-only-key")
    monkeypatch.setattr(seedream, "_submit_task", lambda *a: response("https://example.test/image"))
    async def fail(url):
        raise seedream.ImageGeneratorError("Generated image download failed.")
    monkeypatch.setattr(seedream, "_download_result", fail)
    async def scenario():
        seedream.IMAGE_TASK_CACHE["download-fail"] = {
            "status": "PENDING", "created": time.monotonic(), "work": None,
            "reference_data_url": "data:image/jpeg;base64,test", "prompt": "prompt",
        }
        await seedream.check_optimized_image_task("download-fail")
        await seedream.IMAGE_TASK_CACHE["download-fail"]["work"]
        result = await seedream.check_optimized_image_task("download-fail")
        assert result["status"] == "FAILED" and not result["optimized_image_url"]
        seedream.IMAGE_TASK_CACHE.clear()
    asyncio.run(scenario())
