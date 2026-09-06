# Async redesign image tasks

The old route awaited Wan submission, repeated status fetches and a 90-second
image download in one HTTP request. This created a long-request failure risk
consistent with the reported browser error; the exact proxy disconnect was not
independently observed in Render logs.

The new POST /api/redesign returns the existing rule plan plus image_task_id and
image_generation_status=PENDING immediately after provider submission. It does
not poll or download. Submission's application wait is bounded to 5 seconds
(excluding request-body transfer and rule processing); SDK request_timeout is 4
seconds. Provider latency is not guaranteed. A timed-out synchronous SDK call
may finish in its worker thread, so submission is never automatically retried.

GET /api/redesign/image-status/{task_id} returns a short cached snapshot and
starts at most one background SDK fetch for that task. While fetching or saving,
it returns PENDING/RUNNING. SUCCEEDED means the image is saved and browser-ready,
not merely that Wan finished. The provider URL stays internal. A single worker
and download lock prevent repeated fetches/downloads on concurrent status checks.
PNG decoding/saving runs off the event loop. Download has a 35-second overall
deadline; SDK status waits have an 8-second application deadline. Neither blocks
the HTTP status response. FAILED carries a sanitized error, never a signed URL
or API key. Unknown tasks fail clearly instead of fetching arbitrary provider IDs.

MVP in-memory task cache: use one process/worker and one instance. Restart/deploy
loses task state; users must regenerate. Completed/idle entries older than one
hour are pruned on new submission; capacity is 1024. Generated images remain on
the existing ephemeral /generated mount. Durable shared storage/queues would be
needed before scaling workers or replicas; not introduced in this patch.

The frontend retains the plan immediately and polls every 2500 ms, at most 20
times (approximately 50 seconds plus individual HTTP response time). Each fetch
has its own deadline. It loads the saved URL into afterImage, animates 100 to 50,
and enables pointer interaction only with a loaded image. Replacement uploads
invalidate old results. Replay never submits a new task. Explicit regeneration
does; the button is disabled during generation. Network errors show a readable
Chinese message while console.error retains developer details.

## Validation

- `python -m pytest -q`: 62 passed (two dependency deprecation warnings).
- `node tests/test_frontend_image_poll.cjs`: frontend script syntax and real
  polling-function success/failure/timeout/missing-URL/replay checks passed.
- Regression test holds a simulated download unfinished and confirms POST
  returns before any provider fetch/download; repeated GET requests still return
  promptly and only one download runs. Terminal cache hits do not fetch again.
- Tests isolate provider calls; no paid live Qwen/Wan run or browser visual
  acceptance is claimed by these results.

## Browser acceptance after deployment

Upload an image. Network should show POST /api/analyze, then POST /api/redesign
returning PENDING and image_task_id while the image is unfinished. Next, multiple
GET /api/redesign/image-status/{id} requests should appear. On SUCCEEDED, inspect
optimized_image_url and confirm a separate successful /generated/*.png request.
AFTER must use that URL. Replay should add no new POST. Regenerate should create
one new task. Render logs distinguish [WAN] submitted, [WAN STATUS] and
[WAN DOWNLOAD]. This patch has not been pushed or deployed.
