from html.parser import HTMLParser
from pathlib import Path


HTML = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def test_static_user_visible_copy_is_chinese():
    parser = VisibleText()
    parser.feed(HTML)
    visible = " ".join(parser.parts)
    banned = ["PackLess AI", "PACKAGING WORKBENCH", "UPLOADED PACKAGE", "AI REDESIGN",
              "REDESIGN PRESCRIPTION", "ORIGINAL / BEFORE", "CONCEPTUAL REDESIGN",
              "ENVIRONMENT", "BUSINESS", "SUPPLY CHAIN", "RECOMMENDED", "BALANCED SOLUTION"]
    assert not [text for text in banned if text in visible]


def test_backend_display_translation_layer_is_present():
    assert "DISPLAY_TRANSLATIONS" in HTML
    assert "function localizeBackendText" in HTML
    for machine_value in ("plastic_film", "paperboard", "replace_material", "low_risk", "PENDING"):
        assert machine_value in HTML


def test_impact_cards_keep_values_compact_and_explain_no_change():
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in HTML
    assert 'id="impactWeightReason"' in HTML
    assert 'id="impactPlasticReason"' in HTML
    assert 'id="impactSpaceReason"' in HTML
    assert 'id="impactRecycleReason"' in HTML
    assert 'setImpact("Plastic","0克 → 0克"' in HTML
    assert "当前推荐方案没有批准会降低包装质量的结构动作" in HTML
    assert "当前推荐方案未批准外盒缩容" in HTML


def test_score_breakdown_uses_structured_product_ui():
    assert "score-summary" in HTML
    assert "score-factor" in HTML
    assert "factor-meter" in HTML
    assert "factor-tags" in HTML
    assert "建议工程验证" in HTML
    assert "材料成本变化约" not in HTML
    assert "待实测 %" not in HTML
    assert "待实测 → 待实测" not in HTML
    assert "暂无法估算" in HTML
    assert "carbon-values" in HTML
