"""Read-only material references. No model calls, training, or guessed mass.

An exact lexical match is not proof of material identity or recycled content.
Carbon results are reference-factor estimates, never certified package LCAs.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
logger = logging.getLogger(__name__)


def _load(relative: str, expected: type, data_dir: Path | None = None):
    try:
        value = json.loads(((data_dir or DATA_DIR) / relative).read_text(encoding="utf-8-sig"))
        if not isinstance(value, expected):
            raise ValueError("Unexpected root type")
        return value
    except (OSError, ValueError, UnicodeError):
        logger.warning("[MATERIAL_DATA] unavailable or invalid data: %s", relative)
        return expected()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def load_packaging_data(data_dir: Path | None = None) -> list[dict]:
    return [r for r in _load("processed/taco_normalized.json", list, data_dir) if isinstance(r, dict)]


def load_emission_factors(data_dir: Path | None = None) -> list[dict]:
    valid = []
    for row in _load("processed/defra_emission_factors.json", list, data_dir):
        if not isinstance(row, dict):
            continue
        value, original = _number(row.get("factor_kgco2e_per_kg")), _number(row.get("original_value"))
        if (value is not None and original is not None and row.get("conversion_divisor") == 1000
                and row.get("original_unit") == "kg CO2e/tonne" and row.get("verified") is True
                and math.isclose(value, original / 1000, rel_tol=1e-12, abs_tol=1e-12)
                and all(isinstance(row.get(k), str) and row[k] for k in ("factor_id", "material_subtype", "material_origin", "source"))):
            valid.append(row)
    return valid


def normalize_material_name(name: str, data_dir: Path | None = None) -> dict:
    key = " ".join(name.casefold().split()) if isinstance(name, str) else ""
    mapping = _load("mappings/material_factor_mapping.json", dict, data_dir).get("aliases")
    entry = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(entry, dict) or not isinstance(entry.get("material"), str) or entry.get("match_type") not in ("exact", "inferred", "unknown"):
        entry = {"material": "unknown", "match_type": "unknown"}
    match = entry["match_type"]
    return {
        "input_material": name if isinstance(name, str) else "",
        "material": entry["material"],
        "match_type": "inferred_but_ambiguous" if match == "inferred" else match,
        "confidence": 1.0 if match == "exact" else 0.4 if match == "inferred" else 0.0,
        "requires_validation": match != "exact",
    }


def get_emission_factor(material_name: str, data_dir: Path | None = None,
                        *, origin: str = "primary_material_production") -> dict:
    result = normalize_material_name(material_name, data_dir)
    result.update(factor_kgco2e_per_kg=None, source=None, factor_available=False,
                  material_origin=origin, origin_requires_confirmation=True,
                  estimated=True, hypothesis="Reference factor; confirm material identity, origin and geographic applicability.")
    if result["match_type"] != "exact":
        return result
    matches = [r for r in load_emission_factors(data_dir)
               if r["material_subtype"] == result["material"] and r["material_origin"] == origin]
    if len(matches) != 1:
        result.update(requires_validation=True, confidence=0.0, data_error="Factor unavailable or duplicate")
        return result
    factor = matches[0]
    result.update(factor_available=True, factor_kgco2e_per_kg=factor["factor_kgco2e_per_kg"],
                  source=factor["source"], provenance=factor)
    return result


def get_material_reference(material_name: str, data_dir: Path | None = None) -> dict:
    result = get_emission_factor(material_name, data_dir)
    # Dataset counts are references, not a calibrated visual-classifier confidence.
    key = material_name.casefold().strip() if isinstance(material_name, str) else ""
    result["recognition_reference_count"] = sum(
        any(isinstance(m, str) and m.casefold().strip() == key for m in
            ((r.get("raw_fields") or {}).get("analysis") or {}).get("materials", []))
        for r in load_packaging_data(data_dir)
        if isinstance(r.get("raw_fields"), dict) and isinstance(r["raw_fields"].get("analysis"), dict)
    )
    result["recognition_reference_note"] = "User-supplied predictions; not training data or verified ground truth"
    return result


def calculate_material_carbon(material_name: str, weight_kg: float | None = None,
                              data_dir: Path | None = None, *, origin: str = "primary_material_production") -> dict:
    result = get_emission_factor(material_name, data_dir, origin=origin)
    mass = _number(weight_kg)
    result.update(weight_kg=mass, requires_weight_measurement=mass is None,
                  estimated_material_co2e_kg=None)
    if mass is not None and result["factor_available"]:
        total = mass * result["factor_kgco2e_per_kg"]
        if math.isfinite(total):
            result["estimated_material_co2e_kg"] = total
    return result


def build_carbon_data(analysis: dict) -> dict:
    packaging = analysis.get("packaging")
    materials = packaging.get("materials", []) if isinstance(packaging, dict) else []
    references = []
    for item in materials if isinstance(materials, list) else []:
        if not isinstance(item, dict):
            continue
        # Image-derived estimates and package totals must never become per-material mass.
        verified = item.get("material_verified") is True
        mass = item.get("weight_kg") if verified and item.get("weight_source") in ("measured", "user_supplied") else None
        origin = item.get("material_origin", "primary_material_production")
        ref = calculate_material_carbon(item.get("material", ""), mass, origin=origin)
        ref.update(component=item.get("component", ""), identification_confidence=_number(item.get("confidence")),
                   requires_validation=True, material_identity_verified=verified,
                   origin_requires_confirmation="material_origin" not in item)
        references.append(ref)
    # Explicit completeness is required to claim a package total; otherwise only subtotals.
    complete = packaging.get("bill_of_materials_complete") is True if isinstance(packaging, dict) else False
    complete = complete and isinstance(materials, list) and len(references) == len(materials)
    totals = [r["estimated_material_co2e_kg"] for r in references]
    total = sum(totals) if complete and totals and all(v is not None for v in totals) else None
    if total is not None and not math.isfinite(total):
        total = None
    return {
        "factor_available": any(r["factor_available"] for r in references),
        "materials": references, "estimated_total_co2e_kg": total,
        "requires_weight_measurement": not references or any(r["requires_weight_measurement"] for r in references),
        "requires_complete_bill_of_materials": not complete,
        "requires_validation": True, "estimated": True,
        "hypothesis": "Material procurement reference estimate only. No inferred weight, full-life-cycle footprint or carbon saving is asserted.",
        "environment_score_basis": "Existing rule-based score unchanged; DEFRA references supply auditable material evidence, not measured score calibration.",
    }
