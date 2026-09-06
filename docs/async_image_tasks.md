# Async redesign image tasks

The old route awaited Wan submission, repeated status fetches and a 90-second
image download in one HTTP request. This created a long-request failure risk
consistent with the reported browser error; the exact proxy disconnect was not
independently observed in Render logs.

The new POST /api/redesign returns the existing rule plan plus image_task_id and
image_generation_status=PENDING immediately after provider submission. It does
not poll or download. Submission's application wait is bounded to 45 seconds
(excluding request-body transfer and rule processing); SDK request_timeout is
(10, 30): 10-second connect and 30-second read timeout. The installed SDK forwards
this tuple to requests.Session.post, verified by a transport-level test. The
frontend POST deadline is 55 seconds so it does not abort before the backend.
The previous explicit request_timeout=4, outer 5-second deadline, and frontend
15-second deadline were too short for a slow task acknowledgement.
Provider latency is not guaranteed. A timed-out synchronous SDK call
may finish in its worker thread, so the application does not automatically
resubmit. The installed SDK itself retries ConnectionError once; its existing
behavior is not changed. ReadTimeout is not retried. Logs show [WAN SUBMIT] start,
success/task_id/elapsed, or timeout kind/elapsed and sanitized diagnostic detail.
The user receives "AI image task submission timed out." rather than transport
internals, mapped to a Chinese submission-timeout message by the frontend.

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

- `python -m pytest -q`: 68 passed (two dependency deprecation warnings).
- A simulated 5.2-second submission succeeds with a task ID without polling.
  Connect/read timeout, missing task ID, non-200 responses and the real installed
  SDK's timeout-parameter forwarding are covered.
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
