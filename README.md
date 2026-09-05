# PackLess AI Backend MVP

FastAPI backend for Qwen vision-powered packaging analysis, rule-guided redesign recommendations, Wan-generated packaging concepts, and a material library. This phase intentionally contains no database.

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

The default vision model is `qwen3-vl-plus`, and the default image model is `wan2.6-image`. They can optionally be overridden with `DASHSCOPE_VISION_MODEL` and `DASHSCOPE_IMAGE_MODEL`.

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

Image analysis is implemented in `app/services/ai_analyzer.py`. The four-layer functional, hard-constraint, optimization, and business/supply-chain decision system lives in `app/services/rule_engine.py`; `app/services/redesign_service.py` selects rules for the three risk profiles and computes the weighted recommendation. Prompt construction is isolated in `app/services/prompt_builder.py`. Wan image editing uses an asynchronous task in `app/services/image_generator.py`: submit, poll every 2.5 seconds for up to 10 attempts, download the successful result, and serve it at `/generated/<filename>`. Render's local filesystem is ephemeral, so generated files survive only while the current instance filesystem remains available.

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

Add `DASHSCOPE_API_KEY` under the Render service's **Environment** settings before deploying. Do not commit a real `.env` file.

If this project is stored inside a larger repository, set Render's **Root Directory** to `packless-backend`. Otherwise leave Root Directory blank.
