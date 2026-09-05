from __future__ import annotations

from dataclasses import dataclass
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
        return min(1.0, max(0.0, float(value)))
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
        FUNCTION_DECORATION: ("decoration", "ribbon", "sleeve", "window", "foil stamp"),
    }
    for function, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            functions.append(function)
    return functions or [FUNCTION_PROTECTION]


def functional_check(analysis: dict[str, Any]) -> list[FunctionalCheck]:
    checks: list[FunctionalCheck] = []
    for component in _components(analysis):
        functions = _component_functions(component)
        estimated = not bool(component.evidence) or component.confidence < 0.8
        checks.append(
            FunctionalCheck(
                target=component.name,
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

    if any(term in product_text for term in ("food", "beverage", "snack", "食品", "饮料")):
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


def optimization_rules(
    analysis: dict[str, Any],
    checks: list[FunctionalCheck],
    constraints: list[HardConstraint],
) -> list[OptimizationOpportunity]:
    packaging = analysis.get("packaging") or {}
    diagnosis = analysis.get("diagnosis") or {}
    components = _components(analysis)
    issue_text = " ".join(str(tag) for tag in diagnosis.get("issue_tags") or []).lower()
    try:
        layers = int(packaging.get("layers")) if packaging.get("layers") is not None else None
    except (TypeError, ValueError):
        layers = None
    try:
        utilization = (
            float(packaging.get("space_utilization"))
            if packaging.get("space_utilization") is not None
            else None
        )
    except (TypeError, ValueError):
        utilization = None

    opportunities: list[OptimizationOpportunity] = []
    decorative = [
        check.target
        for check in checks
        if FUNCTION_DECORATION in check.functions
        and FUNCTION_PROTECTION not in check.functions
        and FUNCTION_BARRIER not in check.functions
    ]
    if (layers is not None and layers > 2) or decorative or "excess" in issue_text:
        target = ", ".join(decorative) or "secondary packaging layers"
        opportunities.append(
            _opportunity(
                "R01",
                target,
                "reduce_layers",
                "Remove or combine one non-essential secondary/decorative layer while retaining all protective and barrier functions.",
                "Multiple or decorative layers may duplicate non-protective functions.",
                "Fewer components and less material use; magnitude remains unquantified.",
                "medium",
                "medium",
                0.78 if layers is not None else 0.55,
                True,
                "Layer redundancy is inferred and must be confirmed with a component/function audit.",
            )
        )

    if (utilization is not None and utilization < 75) or "space" in issue_text or "oversize" in issue_text:
        opportunities.append(
            _opportunity(
                "R02",
                "outer box and internal layout",
                "reduce_volume",
                "Evaluate a 15–25% outer-volume reduction and tighter layout, subject to transport-protection validation.",
                "Low visible space utilization indicates avoidable void volume.",
                "Lower material and transport-volume demand; percentage is a design target, not a measured outcome.",
                "low",
                "medium",
                0.82 if utilization is not None else 0.5,
                True,
                "Volume reduction is estimated from visible/analysed utilization; dimensional data are unavailable.",
            )
        )

    film_components = [component for component in components if "film" in component.text or "wrap" in component.text]
    plastic_trays = [
        component
        for component in components
        if "tray" in component.name.lower() and any(term in component.material.lower() for term in PLASTIC_TERMS)
    ]
    food_constraint = any(item.constraint_id == "HC_FOOD_SAFETY" for item in constraints)
    for component in film_components:
        film_functions = next((check.functions for check in checks if check.target == component.name), [])
        functional_barrier = any(
            function in film_functions
            for function in (FUNCTION_SEALING, FUNCTION_MOISTURE, FUNCTION_BARRIER)
        )
        if functional_barrier or food_constraint:
            change = "Lightweight or simplify the film only after seal, barrier and product-safety validation; do not remove it by default."
            action = "lightweight_plastic_film"
        else:
            change = "Remove the non-functional outer plastic film."
            action = "remove_plastic_film"
        opportunities.append(
            _opportunity(
                "R03",
                component.name,
                action,
                change,
                "Visible plastic film is a plastic-reduction candidate, but its function must be preserved.",
                "Potential plastic reduction; no unsupported mass or carbon value is claimed.",
                "medium" if functional_barrier else "low",
                "medium",
                component.confidence,
                functional_barrier or food_constraint,
                "Film necessity is inferred from appearance; seal/barrier specifications were not supplied.",
            )
        )
    for component in plastic_trays:
        opportunities.append(
            _opportunity(
                "R03",
                component.name,
                "replace_inner_tray",
                f"Replace the {component.material} tray with molded pulp only if drop, abrasion, moisture and fit tests pass.",
                "A fiber-based tray may retain cushioning while reducing virgin plastic complexity.",
                "Potential plastic reduction and easier fiber-stream separation; outcome is unquantified.",
                "medium",
                "medium",
                component.confidence,
                True,
                "Molded pulp suitability is a hypothesis pending performance and supplier trials.",
            )
        )

    unique_materials = {component.material.lower() for component in components if component.material.lower() != "unknown"}
    if len(unique_materials) > 2 or "mixed material" in issue_text:
        opportunities.append(
            _opportunity(
                "R04",
                "multi-material packaging system",
                "simplify_materials",
                "Consolidate compatible non-contact components into fewer, readily separable material families without removing required barriers.",
                "Fewer material families can improve sorting and simplify procurement/assembly.",
                "Potentially better recyclability and easier separation; no precise uplift is asserted.",
                "medium",
                "medium",
                0.76 if len(unique_materials) > 2 else 0.52,
                True,
                "Material identities and recycling compatibility require specification-level confirmation.",
            )
        )

    fiber_components = [component for component in components if any(term in component.material.lower() for term in FIBER_TERMS)]
    if fiber_components:
        target = fiber_components[0]
        opportunities.append(
            _opportunity(
                "R05",
                target.name,
                "increase_recycled_content",
                f"Evaluate certified recycled-content {target.material} while preserving print, strength and applicable product-contact requirements.",
                "The existing fiber component may accept recycled content without changing its primary function.",
                "Potential virgin-material displacement; exact benefit requires supplier and LCA data.",
                "low",
                "low",
                target.confidence,
                True,
                "Recycled-content availability, visual quality and strength are not yet verified.",
            )
        )

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
            for function in (FUNCTION_PROTECTION, FUNCTION_CUSHIONING, FUNCTION_SEALING, FUNCTION_BARRIER)
        )
    }
    for opportunity in selected:
        removes_component = opportunity.action in {"remove_component", "remove_plastic_film"}
        if removes_component and opportunity.target in protected_targets:
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
