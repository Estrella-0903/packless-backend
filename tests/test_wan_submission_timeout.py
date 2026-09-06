import asyncio
import json
import time

import pytest
import requests

from app.services import image_generator as wan


@pytest.fixture(autouse=True)
def isolated_submission(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-secret-key")
    monkeypatch.setattr(wan, "_normalized_data_url", lambda _: "data:image/jpeg;base64,AA==")
    wan.IMAGE_TASK_CACHE.clear()
    yield
    wan.IMAGE_TASK_CACHE.clear()


def success():
    return {"status_code": 200, "output": {"task_id": "slow-task", "task_status": "PENDING"}}


def test_installed_sdk_forwards_timeout_tuple_to_requests(monkeypatch):
    seen = []
    def post(session, *args, **kwargs):
        seen.append(kwargs["timeout"])
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps({"output": {"task_id": "transport-test", "task_status": "PENDING"}}).encode()
        result.headers["Content-Type"] = "application/json"
        return result
    monkeypatch.setattr(requests.Session, "post", post)
    result = wan._submit_task("data:image/jpeg;base64,AA==", "test", "test-secret-key")
    assert seen == [(10, 30)]
    assert wan._output_value(result, "task_id") == "transport-test"


def test_slow_submission_exceeding_old_deadline_succeeds(monkeypatch):
    def submit(*args):
        time.sleep(5.2)
        return success()
    monkeypatch.setattr(wan, "_submit_task", submit)
    def forbidden(*args, **kwargs):
        raise AssertionError("Submission must not wait for image generation")
    monkeypatch.setattr(wan.ImageGeneration, "fetch", forbidden)
    started = time.monotonic()
    result = asyncio.run(wan.submit_optimized_image_task(b"fixture", "prompt"))
    elapsed = time.monotonic() - started
    assert 5 < elapsed < 30
    assert result["success"] and result["task_id"] == "slow-task"
    assert result["status"] == "PENDING"


@pytest.mark.parametrize("exception,kind", [(requests.ConnectTimeout,"connect_timeout"), (requests.ReadTimeout,"read_timeout")])
def test_timeout_sanitized_and_not_resubmitted(monkeypatch, capsys, exception, kind):
    calls = []
    def fail(*args):
        calls.append(1)
        raise exception("HTTPSConnectionPool test-secret-key Read timed out")
    monkeypatch.setattr(wan, "_submit_task", fail)
    result = asyncio.run(wan.submit_optimized_image_task(b"fixture", "prompt"))
    assert len(calls) == 1
    assert result == {"success": False, "task_id": "", "status": "FAILED", "error": "AI image task submission timed out."}
    logs = capsys.readouterr().out
    assert kind in logs and "elapsed=" in logs and "HTTPSConnectionPool" in logs
    assert "test-secret-key" not in logs


@pytest.mark.parametrize("reply,error", [
    ({"status_code": 200, "output": {}}, "no valid task_id"),
    ({"status_code": 503, "message": "internal provider detail"}, "rejected by the provider"),
])
def test_provider_errors(monkeypatch, reply, error):
    monkeypatch.setattr(wan, "_submit_task", lambda *args: reply)
    result = asyncio.run(wan.submit_optimized_image_task(b"fixture", "prompt"))
    assert not result["success"] and not result["task_id"]
    assert error in result["error"]
    assert "internal provider detail" not in result["error"]
