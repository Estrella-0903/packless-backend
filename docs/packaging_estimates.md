# Before / After estimation policy

This supersedes the earlier demo policy of leaving all unmeasured after values
null. Estimates are deterministic scenarios; neither classifier training nor
new measurement claims are introduced. Wan task submission, polling and the
comparison slider are unchanged.

`app/services/packaging_estimator.py` owns the six estimation functions and the
orchestrator. Existing numeric metric fields remain; each side adds
`metric_provenance`, keyed by metric name, with value, source, range, confidence,
estimated, requires_validation and hypothesis. Source is measured / estimated /
inferred / pending. Ranges are configured demo assumptions, not confidence
intervals. Confidence values are heuristic, not statistically calibrated.

## Rules

- Layers: count distinct named visible components excluding labels/printing,
  with AI layer count as fallback. Clamp 1–8. Components approximate layers; they
  are not proof of nesting. Selected R01 removes one, never below one.
- Plastic: film 2–12 g (6 default), small tray 10–35 g (24), other supported tray
  25–80 g (40), bag 3–20 g (8). Optional visual_fraction 0–1 selects a bounded
  conservative point; evidence text supplies small/medium cues. Unsupported
  plastic shapes stay pending. Known visible components with no plastic identified
  yield 0 g, explicitly AI estimated; hidden plastic is not ruled out. Sum capped
  at 500 g. R03 may remove film, replace a tray or lightweight film only for an
  approved matching target and action. Replacement fiber is not plastic.
- Total mass: supported small paper box 40–100 g (70); medium/gift box 100–300 g
  (180); large rigid/gift box 250–700 g (420); unsized paper box 40–300 g (120).
  Existing bounded image mass can be used with visible components. Total includes
  packaging only and is bounded to 10–2000 g. R01/R02 use 10% reductions each;
  approved film removal subtracts the modeled film mass. Tray replacement alone
  does not assert net mass savings. Total is not allowed below modeled plastic.
- Utilization: valid AI percentages are retained; fractions strictly between 0
  and 1 are converted to percent. Invalid/ambiguous 1, NaN, negatives or >95 are
  replaced by visual bands rather than displayed as 1%. Very low 30–45 (38), low
  45–60 (48), medium 60–75 (65), high 75–90 (82). With visible packaging but no
  stronger cue, medium is an explicitly low-confidence prior, not a segmentation
  result. R02 adds 20 percentage points, capped at 95. Near the ceiling, the actual
  increase may be less than 10 points. No geometry evidence means pending.
- Recyclability: paper-only 80; paper+plastic 65; paper+tray+film 50; other mixed
  or uncertain composition 40. Selected plastic reduction +10, simplification
  +12, recycled-content rule +5, clamped 0–100. It is a rule score, not certification.
  The model's old 1/100 is not used as a rule score.

Before values can be supplied as measurements through
`measurements.before.<metric> = {"value": 4, "source": "measured", "evidence":
"manual disassembly"}`. Values must be numeric, finite and within metric bounds.
This is caller-provided provenance, not verification by the application. Planned
after values are inferred even when unchanged from measured before values.

## Integration and carbon

Redesign first computes bounded baseline layers/utilization for the existing rule
engine, avoiding malformed AI 1%/1-layer values suppressing valid opportunities.
It does not mutate the uploaded analysis. Rule implementation, hard-constraint
filter and scoring formulas are unchanged. Only the recommended option's selected
opportunities affect displayed after estimates; not every potential rule is used.

Carbon is under `carbon_data.visual_estimate.before/after`, separately from the
existing stricter measured-BOM fields. One identified material can use modeled
total mass. For a supported paper+plastic BOM, estimate each plastic component
and allocate residual mass to the one paper subtype; never multiply total package
mass by every factor. Missing factor or unallocated composition yields null, not
zero. After substitution/simplification/recycled-content changes without an
identified new BOM remain pending. Provider-supplied factor values are not trusted;
the estimator queries the local DEFRA data service. 300 g paperboard gives
0.358 kg CO₂e (rounded estimate, primary-material scenario), not measured carbon.

Frontend displays per-metric Chinese provenance and this persistent notice:
“以下指标为AI/规则估算，最终以实际测量和工程验证为准。”
Carbon is labeled AI估算 and notes its procurement-factor boundary.

## Test evidence (not the user's current image)

No current gift-box image or corresponding analysis JSON was attached to this
request. A synthetic fixture uses paperboard outer gift box, small PET tray and
decorative plastic film, with deliberately malformed layers/space/score=1.

With the actual rule engine, recommended balanced selects R01/R05:

|Metric|Before|After|Provenance|
|---|---:|---:|---|
|Layers|3|2|AI estimate → rule inference|
|Plastic g|30|30|AI estimate → rule inference|
|Total packaging g|180|162|AI estimate → rule inference|
|Utilization %|48|48|AI estimate → rule inference|
|Recyclability /100|50|55|Rule inference|

Plastic and utilization do not improve here because the recommended plan did not
select those actions. An isolated approved R01/R02/R03 film removal/R04 scenario
produces 3→2 layers, 30→24 g plastic, 180→140 g total, 48→68%, 50→72 points.
These are two different rule selections, not fabricated results for one image.
Before fixture carbon is 0.289 kg CO₂e, AI estimated; after carbon remains pending
because the selected recycled-material composition has no specified new BOM.

Tests cover deterministic outputs, bounds, zero vs unknown, fraction handling,
measured provenance, no change without approved rules, target matching, carbon
factor multiplication, and integration with the real rule engine. Neither these
tests nor their numbers constitute a live Qwen image evaluation.
