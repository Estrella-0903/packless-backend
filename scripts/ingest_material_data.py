"""Offline, reproducible ingestion. Never calls an AI API or extracts ZIP paths.

Usage: python scripts/ingest_material_data.py --source-dir <supplied directory>
Requires requirements-data.txt. Runtime services only require generated JSON.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE = "UK Government DEFRA 2024 Greenhouse Gas Conversion Factors"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export(name, rows):
    write_json(DATA / "processed" / f"{name}.json", rows)
    with (DATA / "processed" / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def audit_fields(records):
    fields = sorted({key for row in records for key in row})
    return {key: {
        "missing_rate": sum(key not in row or row[key] is None for row in records) / len(records),
        "empty_rate": sum(row.get(key) in (None, "", []) for row in records) / len(records),
        "types": dict(Counter(type(row[key]).__name__ for row in records if key in row)),
    } for key in fields}


def ingest(source_dir):
    taxonomy = read_json(DATA / "mappings/packaging_taxonomy.json")
    labels = taxonomy["labels"]
    c_path = source_dir / "c_results_all.json"
    records = read_json(c_path)
    if not isinstance(records, list) or not records or not all(isinstance(x, dict) and isinstance(x.get("analysis"), dict) for x in records):
        raise ValueError("Unsupported C input shape; audit source before changing the adapter")
    normalized = []
    for index, raw in enumerate(records):
        analysis = raw["analysis"]
        components = analysis.get("components", [])
        mapped = sorted({labels.get(str(c).casefold(), "unknown") for c in components})
        category = mapped[0] if len(mapped) == 1 else "other_packaging" if mapped and "unknown" not in mapped else "unknown"
        materials = analysis.get("materials", [])
        material = materials[0] if len(materials) == 1 else "unknown"
        normalized.append({
            "sample_id": f"taco_prediction_{index:04d}", "source_dataset": "TACO",
            "source_attribution": "user_supplied; dataset membership not independently verified",
            "image_name": raw.get("source_file"), "object_category": analysis.get("package_type", "unknown"),
            "packaging_category": category, "mapped_categories": mapped,
            "material_family": {"plastic film": "plastic", "cardboard": "paper", "paperboard": "paper", "aluminum": "metal"}.get(material, material),
            "material_subtype": material, "confidence": None,
            "is_packaging": True if category != "unknown" else None,
            "source_label": components, "mapping_confidence": 0.7 if category != "unknown" else 0.0,
            "mapping_source": taxonomy["mapping_source"],
            "notes": "Image-level prediction, not ground truth. Materials and components are NOT paired by array index. Multiple materials do not imply a composite laminate.",
            "raw_fields": raw,
        })
    export("taco_normalized", normalized)
    with zipfile.ZipFile(source_dir / "c_results.zip") as archive:
        zipped = {Path(n).stem + ".jpg": json.loads(archive.read(n)) for n in archive.namelist() if n.endswith(".json")}
    duplicates = sum(zipped.get(r.get("source_file")) == r["analysis"] for r in records)
    # Inspect only metadata, retaining split identity and source category IDs.
    packwise = {}
    with zipfile.ZipFile(source_dir / "PackWISE_dataset_v2.zip") as archive:
        readme = archive.read("readme.txt").decode("utf-8", errors="replace")
        for split in ("train", "val", "test"):
            coco = json.loads(archive.read(f"data/{split}.json"))
            names = {c["id"]: c["name"] for c in coco["categories"]}
            counts = Counter(names.get(a["category_id"], "unknown") for a in coco["annotations"])
            packwise[split] = {"images": len(coco["images"]), "annotations": len(coco["annotations"]), "categories": coco["categories"], "category_counts": dict(counts)}
        write_json(DATA / "processed/packwise_metadata.json", {"splits": packwise, "source_readme": readme, "notes": "Metadata audit only; no training or image redistribution."})

    workbook_path = source_dir / "ghg-conversion-factors-2024-condensed_set__for_most_users__v1_1.xlsx"
    workbook = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
    sheet = workbook["Material use"]
    assert sheet["F6"].value == 2024 and sheet["D6"].value == 1.1, "Unexpected workbook version"
    assert sheet["D20"].value == "Primary material production" and sheet["G20"].value == "Closed-loop source", "Unexpected origin columns"
    assert sheet["D21"].value == "kg CO2e" and sheet["G21"].value == "kg CO2e", "Unexpected emissions units"
    factor_mapping = read_json(DATA / "mappings/defra_materials.json")
    factors = []
    seen = set()
    for row_number, row in enumerate(sheet.values, 1):
        label = row[1]
        if label not in factor_mapping:
            continue
        assert label not in seen, f"Duplicate factor row: {label}"
        seen.add(label)
        assert row[2] == "tonnes", f"Unexpected unit at row {row_number}"
        family, subtype = factor_mapping[label]
        for column, origin in (("D", "primary_material_production"), ("G", "closed_loop_source")):
            value = sheet[f"{column}{row_number}"].value
            assert isinstance(value, (int, float)) and value >= 0
            factors.append({
                "factor_id": f"defra2024_{subtype}_{origin}", "material_family": family,
                "material_subtype": subtype, "factor_kgco2e_per_kg": value / 1000,
                "original_value": value, "original_unit": "kg CO2e/tonne", "conversion_divisor": 1000,
                "source": SOURCE, "year": 2024, "verified": True,
                "verification_scope": "Value and unit extracted from supplied workbook, not package material verification",
                "source_file": workbook_path.name, "source_sha256": digest(workbook_path),
                "sheet": "Material use", "cell": f"{column}{row_number}", "source_label": label,
                "material_origin": origin, "system_boundary": "Material procurement / cradle-to-gate; excludes use and end-of-life",
            })
    workbook.close()
    assert seen == set(factor_mapping), "Configured material missing from workbook"
    export("defra_emission_factors", factors)

    manifest = []
    for name, folder in (("c_results_all.json", "taco"), ("c_results.zip", "taco"), ("D_basic_calculation_result.json", "calculation_examples"), (workbook_path.name, "defra"), ("PackWISE_dataset_v2.zip", "packwise")):
        path = source_dir / name
        # Large images stay at source; raw snapshots of the small inputs remain local.
        destination = DATA / "raw" / folder / name
        if folder != "packwise":
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.copyfile(path, destination)
            elif digest(destination) != digest(path):
                raise ValueError(f"Raw snapshot differs; refusing overwrite: {destination.name}")
        manifest.append({"file": name, "bytes": path.stat().st_size, "sha256": digest(path), "raw_copy": folder != "packwise"})
    write_json(DATA / "processed/source_manifest.json", manifest)
    stats = {
        "c_records": len(records), "normalized_records": len(normalized),
        "top_level_fields": audit_fields(records), "analysis_fields": audit_fields([r["analysis"] for r in records]),
        "semantic_fields": {"packaging_type": "analysis.package_type (product sector, not package shape)", "material": "analysis.materials", "image_name": "source_file", "category": "analysis.package_type", "confidence": None, "source": None, "label": None, "prediction": "analysis (inferred role)"},
        "product_category_counts": dict(Counter(r["analysis"].get("package_type") for r in records)),
        "material_counts": dict(Counter(m for r in records for m in r["analysis"].get("materials", []))),
        "packaging_category_counts": dict(Counter(r["packaging_category"] for r in normalized)),
        "mapped_record_count": sum(r["packaging_category"] != "unknown" for r in normalized),
        "component_occurrences": sum(len(r["analysis"].get("components", [])) for r in records),
        "mapped_component_occurrences": sum(str(c).casefold() in labels for r in records for c in r["analysis"].get("components", [])),
        "zip_records": len(zipped), "zip_exact_duplicates": duplicates,
        "defra_factor_count": len(factors), "defra_material_count": len(seen), "packwise_splits": packwise,
        "d_calculation_example": read_json(source_dir / "D_basic_calculation_result.json"),
    }
    write_json(DATA / "processed/ingestion_audit.json", stats)
    print(json.dumps({k: stats[k] for k in ("c_records", "mapped_record_count", "component_occurrences", "mapped_component_occurrences", "zip_exact_duplicates", "defra_factor_count")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    ingest(parser.parse_args().source_dir)
