from __future__ import annotations

import json
from typing import Any


ANALYSIS_SYSTEM_PROMPT = """You are a packaging sustainability analyst. Analyze only what is visible in the image or can be reasonably inferred from visible evidence.

Truthfulness rules:
- Never invent precise measurements, weights, carbon emissions, material identities, or utilization percentages.
- Use null when the image alone is insufficient to support a numeric value.
- For uncertain materials, use \"unknown\" and explain the visible evidence.
- Confidence must reflect visual certainty and be between 0 and 1.
- Scores may be null when there is not enough evidence.
- Do not claim laboratory identification, certification, or lifecycle assessment.

Output rules:
- Return only valid JSON.
- Do not use Markdown or code fences.
- Do not add explanations, introductions, or text outside the JSON object.
- Match the required field names and nesting as closely as possible.
- If uncertain, use null, an empty string, or an empty array.
- Do not invent precise numeric values.

Return one JSON object with this structure:
{
  "product": {"category": "", "product_name": ""},
  "packaging": {
    "layers": null,
    "materials": [
      {"component": "", "material": "", "confidence": 0.0, "evidence": "", "visual_fraction": null, "size_category": "", "functions": []}
    ],
    "space_utilization": null,
    "recyclability_score": null
  },
  "diagnosis": {"overall_score": null, "level": "", "issue_tags": []},
  "environmental_impact": {
    "estimated_packaging_weight_g": null,
    "estimated_plastic_weight_g": null,
    "estimated_co2e_g": null
  },
  "geometry_estimate": {
    "outer_package": {"length_mm": null, "width_mm": null, "height_mm": null, "estimated": true, "confidence": 0.0},
    "product_occupied_ratio": null,
    "estimated_aspect_ratio": null,
    "method": "visual_2d_proxy",
    "confidence": 0.0
  },
  "summary": ""
}
"""

ANALYSIS_USER_PROMPT = """Analyze the uploaded package image and return the required JSON only.
Return only valid JSON. Do not use markdown. Do not add explanations.
If uncertain, use null, an empty string, or an empty array.
Match the required schema as closely as possible and never invent precise values."""


def build_analysis_messages(image_data_url: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": [{"text": ANALYSIS_SYSTEM_PROMPT}]},
        {
            "role": "user",
            "content": [
                {"image": image_data_url},
                {"text": ANALYSIS_USER_PROMPT},
            ],
        },
    ]


def build_visual_change_summary(change_plan: dict[str, Any]) -> str:
    lines = []
    for item in change_plan.get("component_actions", []):
        component, action = item["component"], item["action"]
        if action == "remove":
            lines.append(f"REMOVE {component}: this component must no longer appear.")
        elif action == "resize":
            lines.append(f"RESIZE {component}: reduce outer volume by approximately {(1-item['scale'])*100:.1f}%; {item.get('layout_strategy', '')}. Keep product size unchanged.")
        elif action == "resize_to_fit":
            lines.append(f"Adapt {component} to {item.get('target_component', 'outer box')}; preserve protective fit.")
        elif action == "replace_material":
            lines.append(f"REPLACE {component}: {item.get('from', '')} → {item.get('to', '')}; visibly represent the material, preserve protective shape.")
        elif action == "lightweight":
            lines.append(f"LIGHTWEIGHT {component}: retain continuous sealing/barrier coverage; reduce gauge conditionally, not remove. The visible difference may be subtle.")
        elif action == "integrate_into":
            lines.append(f"SIMPLIFY {component}: remove the separate piece and integrate its decoration into {item['target_component']} as {item['method']}.")
    return "VISUAL CHANGES REQUIRED:\n" + "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1)) if lines else ""


def build_image_generation_prompt(
    analysis_result: dict[str, Any], change_plan: dict[str, Any], after_render_spec: dict[str, Any] | None = None
) -> str:
    analysis = (
        analysis_result["data"]
        if isinstance(analysis_result.get("data"), dict)
        else analysis_result
    )
    product = analysis.get("product") or {}
    category = product.get("category") or "the same product category visible in the reference"
    product_name = product.get("product_name") or "the exact product shown in the reference"
    return f"""Edit the supplied reference image into an optimized packaging version of the same product.
Product category: {category}.
Product identity: {product_name}.

The optimized package must preserve the original image's:
- camera angle
- product position
- composition
- background
- lighting direction
- brand colors
- logo, typography character, and visual identity

Keep the product itself unchanged and keep the brand immediately recognizable. Only modify the packaging structure and packaging materials. The output must visually align with the original image so the two images can be overlaid in a before/after comparison slider.

The following structured plan is the complete set of approved changes:
{json.dumps(change_plan, ensure_ascii=False)}

Authoritative AfterRenderSpec (packaging dimensions must follow this specification):
{json.dumps(after_render_spec or {}, ensure_ascii=False)}

{build_visual_change_summary(change_plan) or 'LOW VISUAL CHANGE: material sourcing only; retain packaging structure. Do not fabricate a dramatic transformation.'}

DO NOT merely restyle or recolor the original package.
The After image must visibly implement the approved structural changes.
Keep the product itself at the same visual scale so packaging reduction is visible.
Box scale is the retained OUTER VOLUME ratio, not an image scaling factor or a multiplier for every linear dimension.
Do not shrink the whole image. Reduce empty packaging space, keep product units unchanged, and adapt named trays to fit.
Preserve named components except for their explicitly approved modifications. REMOVE means the component must no longer appear; REPLACE means the replacement material must be visibly represented; SIMPLIFY means integrate the named feature, not merely recolor it.

Apply only actions explicitly enabled in the plan. Treat disabled actions and empty replacements as prohibited. Never invent an unapproved material substitution. Preserve required protection, sealing and barrier functions. Keep the result realistic and commercially manufacturable.

Output one polished finished-package concept image, not a dieline, engineering sketch, exploded view, wireframe, infographic, redesign board, or unrelated product. Do not add explanatory labels to the image."""
