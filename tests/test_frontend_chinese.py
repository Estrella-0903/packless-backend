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
