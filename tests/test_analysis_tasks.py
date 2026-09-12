import asyncio
import time

import httpx

from app.main import app
from app.schemas.models import AnalysisData
from app.services import analysis_tasks


def _analysis_data() -> AnalysisData:
    return AnalysisData.model_validate(
        {
            "analysis_id": "analysis_async_test",
            "filename": "package.png",
            "product": {"category": "food", "product_name": "snack"},
            "packaging": {"materials": []},
            "diagnosis": {"level": "", "issue_tags": []},
            "environmental_impact": {},
            "summary": "test",
        }
    )


def test_analysis_task_runs_without_holding_the_submit_request(monkeypatch) -> None:
    async def scenario() -> None:
        async def fake_analyze(*args, **kwargs):
            await asyncio.sleep(0)
            return _analysis_data()

        monkeypatch.setattr(analysis_tasks, "analyze_image", fake_analyze)
        monkeypatch.setattr(analysis_tasks, "build_carbon_data", lambda value: {})
        analysis_tasks.ANALYSIS_TASK_CACHE.clear()

        submitted = analysis_tasks.submit_analysis_task(b"image", "image/png", "package.png")
        assert submitted["status"] == "PENDING"
        task_id = submitted["analysis_task_id"]
        await analysis_tasks.ANALYSIS_TASK_CACHE[task_id]["work"]

        finished = analysis_tasks.get_analysis_task(task_id)
        assert finished["status"] == "SUCCEEDED"
        assert finished["result"]["analysis_id"] == "analysis_async_test"

    asyncio.run(scenario())


def test_missing_analysis_task_returns_explanatory_failure() -> None:
    result = analysis_tasks.get_analysis_task("missing")
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "ANALYSIS_TASK_NOT_FOUND"


def test_async_analysis_http_requests_stay_short(monkeypatch) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_analyze(*args, **kwargs):
            started.set()
            await release.wait()
            return _analysis_data()

        monkeypatch.setattr(analysis_tasks, "analyze_image", slow_analyze)
        monkeypatch.setattr(analysis_tasks, "build_carbon_data", lambda value: {})
        analysis_tasks.ANALYSIS_TASK_CACHE.clear()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            began = time.monotonic()
            response = await client.post(
                "/api/analyze",
                headers={"Prefer": "respond-async"},
                files={"image": ("package.png", b"image", "image/png")},
            )
            assert response.status_code == 202
            assert time.monotonic() - began < 0.5
            task_id = response.json()["data"]["analysis_task_id"]
            await asyncio.wait_for(started.wait(), 1)

            pending = await client.get(f"/api/analyze/status/{task_id}")
            assert pending.status_code == 202
            assert pending.json()["data"]["status"] == "RUNNING"

            release.set()
            await analysis_tasks.ANALYSIS_TASK_CACHE[task_id]["work"]
            finished = await client.get(f"/api/analyze/status/{task_id}")
            assert finished.status_code == 200
            assert finished.json()["data"]["analysis_id"] == "analysis_async_test"
        analysis_tasks.ANALYSIS_TASK_CACHE.clear()

    asyncio.run(scenario())
