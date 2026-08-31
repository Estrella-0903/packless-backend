# PackLess AI Backend MVP

FastAPI mock backend for packaging analysis, redesign recommendations, and a material library. This phase intentionally contains no database or real AI integration.

## Requirements

- Python 3.10+

## Install

```bash
pip install -r requirements.txt
```

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

- `POST /api/analyze` — send `multipart/form-data` with an `image` file. Returns mock packaging analysis and preserves the uploaded filename.
- `POST /api/redesign` — send JSON containing an analysis ID and any available packaging context. All request fields are optional for early frontend integration.
- `GET /api/materials` — returns the static mock material library. Its `co2_factor` values are demo parameters, not validated LCA data.

System checks are available at `GET /` and `GET /health`.

## Example requests

```bash
curl -X POST http://127.0.0.1:8000/api/analyze -F "image=@package.jpg"
curl -X POST http://127.0.0.1:8000/api/redesign -H "Content-Type: application/json" -d '{"analysis_id":"analysis_demo_001"}'
curl http://127.0.0.1:8000/api/materials
```

## Test

```bash
pytest -q
```

## Replacing mocks with AI

The routes own HTTP validation and stable response contracts. Replace `build_mock_analysis` and `build_mock_redesign` in `app/mock/mock_data.py` with service/provider calls that perform image analysis, prompt construction, model invocation, and structured response validation. Keep the Pydantic response models in `app/schemas/models.py` as the frontend contract.

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

If this project is stored inside a larger repository, set Render's **Root Directory** to `packless-backend`. Otherwise leave Root Directory blank.
