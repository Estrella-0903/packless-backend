# Seedream redesign image tasks

Seedream 5.0 Pro is called through Volcano Ark's synchronous
`POST /api/v3/images/generations` endpoint. The application preserves its
existing asynchronous browser contract with a local in-memory task adapter.

`POST /api/redesign` validates and normalizes the reference image, creates a
local `seedream_*` task ID, and immediately returns the rule plan with
`image_generation_status=PENDING`. It does not wait for paid image generation.
The first `GET /api/redesign/image-status/{task_id}` starts one background
Seedream call. Concurrent status requests return a short PENDING/RUNNING cache
snapshot and never duplicate the provider request.

The provider request uses:

- `ARK_API_KEY` as a Bearer token;
- model `doubao-seedream-5-0-pro-260628` by default;
- the uploaded image as a normalized JPEG data URL;
- `sequential_image_generation=disabled`, `response_format=url`, 2K output,
  and no watermark.

Model, endpoint and size can be overridden with `SEEDREAM_IMAGE_MODEL`,
`SEEDREAM_API_URL`, and `SEEDREAM_IMAGE_SIZE`. The default endpoint is
`https://ark.cn-beijing.volces.com/api/v3/images/generations`.

Provider URLs stay internal because they may contain temporary credentials.
The result is downloaded, decoded, saved as PNG under `/generated`, and only
then marked SUCCEEDED. FAILED contains a sanitized error without API keys or
signed URLs. A low visual-change score triggers at most one regeneration with a
stronger prompt.

The background generation deadline is 210 seconds, result download deadline is
95 seconds, and the browser polls every 2.5 seconds for up to 90 attempts. The
task cache is process-local, capped at 1024 entries, and prunes idle entries
older than one hour on submission. A durable queue and object storage are still
required before using multiple workers or replicas.

## Validation

- Provider tests verify Ark URL, Bearer auth, model, reference image, output
  size, single-image mode, URL response format and watermark configuration.
- API tests verify the unchanged `success`, `optimized_image_url`,
  `image_generation_failed`, and `image_generation_error` fields.
- Task tests cover PENDING/RUNNING/SUCCEEDED, one provider call, one download,
  timeout, provider rejection, invalid result and credential redaction.
- Tests mock the provider and do not consume Seedream quota.
