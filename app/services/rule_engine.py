from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

from app.schemas.models import FunctionalCheck, HardConstraint, OptimizationOpportunity


FUNCTION_PROTECTION = "protection"
FUNCTION_CUSHIONING = "cushioning"
FUNCTION_SEALING = "sealing"
FUNCTION_MOISTURE = "moisture_protection"
FUNCTION_BARRIER = "barrier"
FUNCTION_DISPLAY = "display"
FUNCTION_TRANSPORT = "transport"
FUNCTION_BRAND = "brand_expression"
FUNCTION_DECORATION = "decoration"

PLASTIC_TERMS = ("plastic", "pet", "pvc", "polyethylene", "polypropylene", "pp", "ps")
FIBER_TERMS = ("paper", "paperboard", "cardboard", "carton", "fiber", "fibre")

RISK_MATRIX = {
    "reduce_layers": {
        "cost": "low",
        "brand_experience": "medium",
        "consumer_experience": "medium",
        "process_compatibility": "medium",
        "material_availability": "low",
        "transport_protection": "medium",
    },
    "reduce_volume": {
        "cost": "medium",
        "brand_experience": "low",
        "consumer_experience": "low",
        "process_compatibility": "medium",
        "material_availability": "low",
        "transport_protection": "high",
    },
    "remove_plastic_film": {
        "cost": "low",
        "brand_experience": "low",
        "consumer_experience": "medium",
        "process_compatibility": "medium",
        "material_availability": "low",
        "transport_protection": "medium",
    },
    "lightweight_plastic_film": {
        "cost": "medium",
        "brand_experience": "low",
        "consumer_experience": "low",
        "process_compatibility": "medium",
        "material_availability": "medium",
        "transport_protection": "high",
    },
    "replace_inner_tray": {
        "cost": "medium",
        "brand_experience": "low",
        "consumer_experience": "medium",
        "process_compatibility": "medium",
        "material_availability": "medium",
        "transport_protection": "high",
    },
    "simplify_materials": {
        "cost": "medium",
        "brand_experience": "low",
        "consumer_experience": "low",
        "process_compatibility": "high",
        "material_availability": "medium",
        "transport_protection": "medium",
    },
    "increase_recycled_content": {
        "cost": "medium",
        "brand_experience": "medium",
        "consumer_experience": "low",
        "process_compatibility": "low",
        "material_availability": "medium",
        "transport_protection": "medium",
    },
}


@dataclass(frozen=True)
class Component:
    name: str
    material: str
    confidence: float
    evidence: str
    declared_functions: tuple[str, ...] = ()
    essential: bool = False
    essential_declared: bool | None = None
    brand_critical: bool = False
    protective_declared: bool | None = None
    barrier_declared: bool | None = None

    @property
    def text(self) -> str:
        return f"{self.name} {self.material}".lower()


@dataclass(frozen=True)
class RuleEngineResult:
    functional_checks: list[FunctionalCheck]
    hard_constraints: list[HardConstraint]
    opportunities: list[OptimizationOpportunity]


def _confidence(value: Any, default: float = 0.55) -> float:
    try:
        number = float(value)
        return min(1.0, max(0.0, number)) if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _components(analysis: dict[str, Any]) -> list[Component]:
    packaging = analysis.get("packaging") or {}
    result: list[Component] = []
    for index, item in enumerate(packaging.get("materials") or []):
        if isinstance(item, dict):
            result.append(
                Component(
                    name=str(item.get("component") or f"component_{index + 1}"),
                    material=str(item.get("material") or "unknown"),
                    confidence=_confidence(item.get("confidence")),
                    evidence=str(item.get("evidence") or ""),
                    declared_functions=tuple(item.get("functions") or ()),
                    essential=item.get("essential") is True,
                    essential_declared=item.get("essential") if isinstance(item.get("essential"), bool) else None,
                    brand_critical=item.get("brand_critical") is True,
                    protective_declared=item.get("protective") if isinstance(item.get("protective"), bool) else None,
                    barrier_declared=item.get("barrier") if isinstance(item.get("barrier"), bool) else None,
                )
            )
        elif isinstance(item, str):
            result.append(Component(f"component_{index + 1}", item, 0.45, ""))
    return result


def _component_functions(component: Component) -> list[str]:
    text = component.text
    functions: list[str] = []
    keyword_map = {
        FUNCTION_PROTECTION: ("box", "carton", "tray", "insert", "bottle", "jar", "shell"),
        FUNCTION_CUSHIONING: ("tray", "insert", "foam", "padding", "filler", "pulp"),
        FUNCTION_SEALING: ("film", "wrap", "seal", "cap", "lid", "pouch"),
        FUNCTION_MOISTURE: ("film", "wrap", "liner", "foil", "coating", "pouch"),
        FUNCTION_BARRIER: ("film", "foil", "liner", "bottle", "jar", "pouch"),
        FUNCTION_DISPLAY: ("box", "carton", "label", "sleeve", "window"),
        FUNCTION_TRANSPORT: ("box", "carton", "tray", "insert", "shipping"),
        FUNCTION_BRAND: ("box", "carton", "label", "sleeve", "print"),
        FUNCTION_DECORATION: ("decorat", "ribbon", "sleeve", "window", "foil stamp", "装饰"),
    }
    for function, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            functions.append(function)
    evidence = component.evidence.lower()
    # Only explicitly non-functional ornamental inserts/outer wraps override
    # generic name heuristics. Supplied protective functions always win.
    purely_decorative = FUNCTION_DECORATION in functions and any(term in evidence for term in ("non-protective", "non-functional", "decoration only", "ornament only", "仅装饰", "无保护"))
    if purely_decorative and not any(term in text for term in ("box", "bottle", "jar", "盒")) and not any(term in evidence for term in ("barrier", "seal", "food contact", "密封", "屏障")):
        functions = [FUNCTION_DISPLAY, FUNCTION_DECORATION]
    if "protective" in component.name.lower().replace("non-protective", "") or "protects" in evidence:
        functions.append(FUNCTION_PROTECTION)
    if any(term in evidence for term in ("sealed", "sealing", "barrier", "密封", "屏障")):
        functions.append(FUNCTION_BARRIER)
    functions = list(dict.fromkeys(functions + list(component.declared_functions)))
    # Explicit visual-analysis flags may rule out generic name heuristics. They do
    # not prove removability; low-confidence candidates remain validation-only.
    if component.protective_declared is False:
        functions = [f for f in functions if f not in (FUNCTION_PROTECTION, FUNCTION_CUSHIONING, FUNCTION_TRANSPORT)]
    if component.barrier_declared is False:
        functions = [f for f in functions if f not in (FUNCTION_BARRIER, FUNCTION_MOISTURE, FUNCTION_SEALING)]
    if not functions and component.protective_declared is False and component.barrier_declared is False:
        return [FUNCTION_DISPLAY]
    return functions or [FUNCTION_PROTECTION]


def functional_check(analysis: dict[str, Any]) -> list[FunctionalCheck]:
    checks: list[FunctionalCheck] = []
    for component in _components(analysis):
        functions = _component_functions(component)
        protective = any(f in functions for f in (FUNCTION_PROTECTION, FUNCTION_CUSHIONING, FUNCTION_TRANSPORT))
        barrier = any(f in functions for f in (FUNCTION_BARRIER, FUNCTION_MOISTURE, FUNCTION_SEALING))
        brand_critical = component.brand_critical or any(t in component.evidence.lower() for t in ("sole logo", "only brand", "mandatory", "唯一品牌", "法定"))
        essential = component.essential or protective or barrier or brand_critical
        estimated = True  # Visual evidence is not functional verification.
        checks.append(
            FunctionalCheck(
                target=component.name,
                material=component.material,
                essential=essential,
                protective=protective,
                barrier=barrier,
                brand_critical=brand_critical,
                decorative=FUNCTION_DECORATION in functions,
                potentially_redundant=not essential and FUNCTION_DECORATION in functions and " or " not in component.name.lower(),
                functions=functions,
                confidence=round(component.confidence, 2),
                estimated=estimated,
                hypothesis=(
                    f"Functions inferred from visible component/material cues: {component.evidence or 'no explicit evidence supplied'}."
                    if estimated
                    else "Functions supported by the supplied visual evidence."
                ),
            )
        )
    return checks


def hard_constraints(
    analysis: dict[str, Any], checks: list[FunctionalCheck]
) -> list[HardConstraint]:
    product = analysis.get("product") or {}
    category = str(product.get("category") or "").lower()
    product_name = str(product.get("product_name") or "").lower()
    product_text = f"{category} {product_name}"
    constraints: list[HardConstraint] = []

    def add(
        constraint_id: str,
        target: str,
        requirement: str,
        reason: str,
        confidence: float,
        requires_validation: bool,
        hypothesis: str,
    ) -> None:
        constraints.append(
            HardConstraint(
                constraint_id=constraint_id,
                target=target,
                requirement=requirement,
                reason=reason,
                confidence=confidence,
                requires_validation=requires_validation,
                estimated=True,
                hypothesis=hypothesis,
            )
        )

    protected_targets = [
        check.target
        for check in checks
        if FUNCTION_PROTECTION in check.functions or FUNCTION_CUSHIONING in check.functions
    ]
    if protected_targets:
        add(
            "HC_PROTECTION",
            ", ".join(protected_targets),
            "Maintain adequate product protection and cushioning performance.",
            "Removing or reducing these components may increase damage risk.",
            0.75,
            True,
            "Protection function is inferred; transit/drop/compression tests are required.",
        )

    if any(term in product_text for term in ("food", "beverage", "snack", "confectionery", "mooncake", "食品", "饮料", "月饼")):
        add(
            "HC_FOOD_SAFETY",
            "primary packaging and product-contact materials",
            "Use compliant food-contact materials and preserve sealing/barrier performance.",
            "Food safety and shelf life cannot be compromised by material reduction.",
            0.9,
            True,
            "Category suggests food contact; compliance and migration testing are required.",
        )

    if any(term in product_text for term in ("electronic", "electronics", "device", "电子", "数码")):
        add(
            "HC_ELECTRONICS_PROTECTION",
            "protective tray, cushioning and barrier system",
            "Preserve impact, vibration, abrasion and any required ESD protection.",
            "Electronic products may be sensitive to shock, abrasion, moisture or static.",
            0.88,
            True,
            "Category suggests electronics; drop, vibration and ESD requirements need confirmation.",
        )

    if product.get("product_name"):
        add(
            "HC_BRAND_DISPLAY",
            "consumer-facing packaging",
            "Keep essential brand recognition and legally required information visible.",
            "Brand recognition and mandatory information affect commercial acceptance.",
            0.8,
            True,
            "Exact brand guidelines and mandatory copy were not supplied.",
        )

    return constraints


def _opportunity(
    rule_id: str,
    target: str,
    action: str,
    recommended_change: str,
    reason: str,
    environment_value: str,
    commercial_risk: str,
    supply_chain_risk: str,
    confidence: float,
    requires_validation: bool,
    hypothesis: str,
) -> OptimizationOpportunity:
    return OptimizationOpportunity(
        rule_id=rule_id,
        target=target,
        action=action,
        recommended_change=recommended_change,
        reason=reason,
        environment_value=environment_value,
        commercial_risk=commercial_risk,
        supply_chain_risk=supply_chain_risk,
        risk_assessment={
            "cost": "unknown",
            "brand_experience": "unknown",
            "consumer_experience": "unknown",
            "process_compatibility": "unknown",
            "material_availability": "unknown",
            "transport_protection": "unknown",
        },
        confidence=round(confidence, 2),
        requires_validation=requires_validation,
        estimated=True,
        hypothesis=hypothesis,
    )


def _is_plastic(component: Component) -> bool:
    value = component.material.lower()
    return "plastic" in value or "塑料" in value or bool(re.search(r"\b(pet|pp|ps|pe|hdpe|ldpe|pvc)\b", value))


def optimization_rules(analysis, checks, constraints) -> list[OptimizationOpportunity]:
    packaging = analysis.get("packaging") or {}
    components = _components(analysis)
    checks_by_name = {c.target: c for c in checks}
    opportunities = []
    constraint_ids = {c.constraint_id for c in constraints}

    def emit(rule, component, action, visual, changes, reason):
        opportunity = _opportunity(rule, component.name, action, reason, reason,
            "Potential resource reduction; quantified results remain estimates.",
            "medium", "medium", component.confidence, True,
            "Conditional concept action; verify component functions, material suitability and engineering performance.")
        for change in changes:
            change.update(rule_id=rule, reason=reason, confidence=component.confidence,
                          requires_validation=True, estimated=True)
        opportunities.append(OptimizationOpportunity.model_validate({
            **opportunity.model_dump(), "visual_impact": visual, "component_actions": changes}))

    for component in components:
        check = checks_by_name[component.name]
        # No generic 'secondary layers' target. Plastic decorative inserts belong
        # to R04 and plastic films to R03, avoiding conflicting duplicate actions.
        candidate = ((check.potentially_redundant and component.confidence >= .65) or (
            component.essential_declared is False
            and component.protective_declared is False
            and component.barrier_declared is False
            and not check.essential and not check.protective and not check.barrier
            and not check.brand_critical and component.confidence >= .4
        ))
        if candidate and component.evidence and not _is_plastic(component) and any(c.protective for c in checks):
            emit("R01", component, "reduce_layers", "high",
                 [{"component": component.name, "action": "remove"}],
                 f"Evaluate removing or integrating the non-essential component {component.name}; retain protection, barriers and essential brand information.")

    try:
        utilization = float(packaging.get("space_utilization"))
    except (TypeError, ValueError):
        utilization = None
    boxes = [c for c in components if any(t in c.name.lower() for t in ("box", "carton", "package", "outer lid", "盒", "箱", "外盖"))]
    outer_boxes = [c for c in boxes if any(t in c.name.lower() for t in ("outer", "rigid", "外"))] or boxes
    # A generic medium prior is not strong geometric evidence for a resize.
    space_meta = (packaging.get("metric_provenance") or {}).get("space_utilization", {})
    prior_only = "medium is a conservative prior" in str(space_meta.get("hypothesis", "")) and "band=medium" in str(space_meta.get("hypothesis", ""))
    geometry_only_fallback = packaging.get("geometry_source") == "rule_fallback" and packaging.get("space_utilization") == 65
    try:
        geometry_confidence = float(packaging.get("geometry_confidence", .55))
    except (TypeError, ValueError):
        geometry_confidence = 0
    try:
        data_scale = float(packaging.get("recommended_outer_volume_ratio"))
    except (TypeError, ValueError):
        data_scale = None
    has_resize_evidence = (
        geometry_confidence >= .55 and data_scale is not None
        and .7 <= data_scale <= .92 and not geometry_only_fallback
    )
    legacy_space_evidence = (
        packaging.get("geometry_confidence") is None
        and utilization is not None and math.isfinite(utilization)
        and 20 <= utilization < 70 and not prior_only and not geometry_only_fallback
    )
    if outer_boxes and (has_resize_evidence or legacy_space_evidence):
        box = outer_boxes[0]
        scale = round(data_scale, 3) if data_scale is not None and .7 <= data_scale < 1 else (.78 if utilization < 45 else .825 if utilization < 60 else .885)
        changes = [{"component": box.name, "action": "resize", "scale": scale,
                    "scale_basis": "outer_volume_ratio", "resize_axis": "overall",
                    "layout_strategy": "reduce void space around products; keep product size unchanged"}]
        changes += [{"component": c.name, "action": "resize_to_fit", "follow_outer_box": True,
                     "target_component": box.name, "preserve_shape": True}
                    for c in components if any(t in c.name.lower() for t in ("tray", "insert", "内托"))]
        emit("R02", box, "reduce_volume", "high", changes,
             f"Target approximately {round((1-scale)*100, 1)}% less outer volume by reducing voids; retain fit, product dimensions and transport protection.")

    for component in components:
        check = checks_by_name[component.name]
        if not _is_plastic(component):
            continue
        name = component.name.lower()
        if any(t in name for t in ("film", "wrap", "薄膜")):
            removable = check.potentially_redundant and not check.barrier
            action = "remove_plastic_film" if removable else "lightweight_plastic_film"
            emit("R03", component, action, "medium" if removable else "low",
                 [{"component": component.name, "action": "remove" if removable else "lightweight",
                   **({} if removable else {"scale": .7, "scale_basis": "film_mass_ratio", "preserve_shape": True})}],
                 "Remove only non-functional decorative plastic film." if removable else "Retain film coverage, seal and barrier function; trial lower gauge only after validation.")
        elif any(t in name for t in ("tray", "insert", "内托")) and not check.potentially_redundant:
            # Sensitive categories/barriers require suitability evidence beyond an
            # image. Do not approve a material replacement by default.
            sensitive = constraint_ids & {"HC_FOOD_SAFETY", "HC_ELECTRONICS_PROTECTION"}
            if not sensitive and not check.barrier:
                emit("R03", component, "replace_inner_tray", "high",
                     [{"component": component.name, "action": "replace_material", "from": component.material,
                       "to": "Molded pulp", "preserve_shape": True}],
                     "Replace this plastic tray with molded pulp while preserving its protective geometry; validate cushioning, abrasion and fit.")

    paper_boxes = [c for c in outer_boxes if any(t in c.material.lower() for t in FIBER_TERMS)]
    if paper_boxes:
        target = paper_boxes[0]
        for component in components:
            check = checks_by_name[component.name]
            if _is_plastic(component) and check.potentially_redundant and "film" not in component.name.lower() and component.confidence >= .65:
                emit("R04", component, "simplify_materials", "medium",
                     [{"component": component.name, "action": "integrate_into", "target_component": target.name,
                       "method": "printed/embossed paper feature", "from": component.material, "to": target.material}],
                     "Integrate the non-protective plastic decoration into the existing paperboard box's print/embossing, eliminating a separate component.")

    fiber = [c for c in components if any(t in c.material.lower() for t in FIBER_TERMS)]
    if fiber:
        component = next((c for c in paper_boxes if c in fiber), fiber[0])
        emit("R05", component, "increase_recycled_content", "low",
             [{"component": component.name, "action": "increase_recycled_content", "from": component.material,
               "to": component.material, "preserve_shape": True}],
             "Evaluate certified recycled content in this existing fiber component; retain geometry, strength, brand appearance and applicable contact compliance.")
    return opportunities


def business_supply_chain_risk_rules(
    opportunities: list[OptimizationOpportunity],
) -> list[OptimizationOpportunity]:
    """Apply auditable business and supply-chain risk rules to approved actions."""
    risk_rank = {"low": 0, "medium": 1, "high": 2, "unknown": 2}
    ranked_risk = {0: "low", 1: "medium", 2: "high"}
    evaluated: list[OptimizationOpportunity] = []
    for opportunity in opportunities:
        assessment = RISK_MATRIX.get(
            opportunity.action,
            {
                "cost": "unknown",
                "brand_experience": "unknown",
                "consumer_experience": "unknown",
                "process_compatibility": "unknown",
                "material_availability": "unknown",
                "transport_protection": "unknown",
            },
        )
        commercial = max(
            (
                assessment["cost"],
                assessment["brand_experience"],
                assessment["consumer_experience"],
            ),
            key=lambda value: risk_rank[value],
        )
        supply_chain = max(
            (
                assessment["process_compatibility"],
                assessment["material_availability"],
                assessment["transport_protection"],
            ),
            key=lambda value: risk_rank[value],
        )
        evaluated.append(
            OptimizationOpportunity.model_validate(
                {
                    **opportunity.model_dump(),
                    "commercial_risk": ranked_risk[risk_rank[commercial]],
                    "supply_chain_risk": ranked_risk[risk_rank[supply_chain]],
                    "risk_assessment": assessment,
                }
            )
        )
    return evaluated


def violates_hard_constraints(
    selected: list[OptimizationOpportunity],
    checks: list[FunctionalCheck],
    constraints: list[HardConstraint],
) -> bool:
    protected_targets = {
        check.target
        for check in checks
        if any(
            function in check.functions
            for function in (FUNCTION_PROTECTION, FUNCTION_CUSHIONING, FUNCTION_SEALING, FUNCTION_BARRIER, FUNCTION_MOISTURE, FUNCTION_TRANSPORT)
        )
        or check.essential or check.brand_critical
    }
    by_name = {check.target: check for check in checks}
    constraint_ids = {c.constraint_id for c in constraints}
    for opportunity in selected:
        removes_component = opportunity.action in {"remove_component", "remove_plastic_film", "reduce_layers", "simplify_materials"}
        if removes_component and opportunity.target in protected_targets:
            return True
        if removes_component and opportunity.target not in by_name:
            return True
        for action in opportunity.component_actions:
            if action.component not in by_name:
                return True
            if action.action in {"remove", "integrate_into"} and action.component in protected_targets:
                return True
            if action.action == "integrate_into" and (action.target_component not in by_name or action.target_component == action.component):
                return True
            if action.action == "replace_material" and (by_name[action.component].barrier or constraint_ids & {"HC_FOOD_SAFETY", "HC_ELECTRONICS_PROTECTION"}):
                return True
        if (
            any(item.constraint_id == "HC_FOOD_SAFETY" for item in constraints)
            and opportunity.action == "replace_food_contact_material"
        ):
            return True
    return False


def run_rule_engine(analysis: dict[str, Any]) -> RuleEngineResult:
    checks = functional_check(analysis)
    constraints = hard_constraints(analysis, checks)
    opportunities = business_supply_chain_risk_rules(
        optimization_rules(analysis, checks, constraints)
    )
    return RuleEngineResult(checks, constraints, opportunities)
