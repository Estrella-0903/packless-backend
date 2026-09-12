# PackLess AI Backend MVP

FastAPI backend for Qwen vision-powered packaging analysis, rule-guided redesign recommendations, Seedream-generated packaging concepts, and a material library. This phase intentionally contains no database.

## Requirements

- Python 3.10+

## Install

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set your Alibaba Cloud Model Studio API key:

```text
DASHSCOPE_API_KEY=your-api-key-here
```

The default vision model is `qwen3-vl-plus`. Image editing uses Volcano Ark Seedream 5.0 Pro (`doubao-seedream-5-0-pro-260628`) and requires `ARK_API_KEY`; `SEEDREAM_IMAGE_MODEL`, `SEEDREAM_API_URL`, and `SEEDREAM_IMAGE_SIZE` are optional overrides.

## Run

```bash
uvicorn app.main:app --reload
```

Run commands from the `packless-backend` directory.

## Server

```text
http://127.0.0.1:8000
```

For a frontend running on the same computer, use `http://127.0.0.1:8000` as the API base URL. A phone, emulator, or container must use the development computer's reachable LAN/host address instead of `127.0.0.1`.

## Swagger

```text
http://127.0.0.1:8000/docs
```

## Main API endpoints

- `POST /api/analyze` — send `multipart/form-data` with an `image` file. Calls Alibaba Cloud Model Studio's Qwen vision model and returns validated structured packaging analysis.
- `POST /api/redesign` — preferably send `multipart/form-data` with `analysis_result` JSON and the original `image`. Legacy JSON analysis context is still accepted; without an image the API returns the rule plan with image fallback enabled.
- `GET /api/materials` — returns the static mock material library. Its `co2_factor` values are demo parameters, not validated LCA data.

System checks are available at `GET /` and `GET /health`.

## Example requests

```bash
curl -X POST http://127.0.0.1:8000/api/analyze -F "image=@package.jpg"
curl -X POST http://127.0.0.1:8000/api/redesign -F 'analysis_result={"analysis_id":"analysis_demo_001","product":{"category":"cosmetics"}}' -F "image=@package.jpg"
curl http://127.0.0.1:8000/api/materials
```

## Test

```bash
pytest -q
```

Image analysis is implemented in `app/services/ai_analyzer.py`. The four-layer functional, hard-constraint, optimization, and business/supply-chain decision system lives in `app/services/rule_engine.py`; `app/services/redesign_service.py` selects rules for the three risk profiles and computes the weighted recommendation. Prompt construction is isolated in `app/services/prompt_builder.py`. Seedream image editing is adapted to the existing local task contract in `app/services/image_generator.py`: `/api/redesign` creates a task, the frontend polls the unchanged status endpoint, and the synchronous Ark result is downloaded and served at `/generated/<filename>`. Render's local filesystem is ephemeral, so generated files survive only while the current instance filesystem remains available.

The browser requests asynchronous packaging analysis with `Prefer: respond-async`. `POST /api/analyze` then returns `202` with an `analysis_task_id`, and the browser polls `GET /api/analyze/status/<task_id>`. This avoids holding one idle HTTP connection open during variable vision-model latency. API clients that omit the header retain the original synchronous response contract.

## Deploy to Render

Create a Render Web Service with this directory (the one containing `requirements.txt`) as the Git repository root.

The included `.python-version` pins Render to Python 3.12.13, matching the verified runtime.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Add both `DASHSCOPE_API_KEY` (image analysis) and `ARK_API_KEY` (Seedream image editing) under the Render service's **Environment** settings before deploying. Do not commit a real `.env` file.

If this project is stored inside a larger repository, set Render's **Root Directory** to `packless-backend`. Otherwise leave Root Directory blank.
