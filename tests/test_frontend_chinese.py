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
    assert "score-adjustments" in HTML
    assert "有效改善校正" in HTML
    assert "低置信度结构动作" in HTML
    assert "保守展示基线" in HTML
    assert "该校正不是额外环境收益" in HTML
    assert "包装减量25% · 塑料减量20% · 碳排改善30%" in HTML
    assert 'kind==="supplyChain"?"supply_chain":kind' in HTML
    assert "item.max_score??item.max_points" in HTML
    assert "暂无法估算，其他已知子项仍正常展示。" in HTML


def test_primary_material_metric_is_dynamic_and_chinese():
    assert "function buildPrimaryMaterialMetric(analysisResult,redesignResult)" in HTML
    assert 'id="materialMetricLabel"' in HTML
    assert 'id="materialMetricBefore"' in HTML
    assert 'id="materialMetricAfter"' in HTML
    assert 'id="materialMetricUnit"' in HTML
    for label in ("包装层数", "塑料使用", "材料种类", "材料复杂度", "纸材用量", "材料结构", "空间利用率", "可回收评分"):
        assert label in HTML
    assert 'data-before-metric="plasticWeight"' not in HTML


def test_analysis_error_preserves_backend_diagnostic_message():
    assert "const responseText=await response.text()" in HTML
    assert "result?.error?.message" in HTML
    assert 'alert(error instanceof Error&&error.message?error.message:' in HTML


def test_analysis_uses_short_polling_requests_instead_of_one_idle_connection():
    assert 'headers:{Prefer:"respond-async"}' in HTML
    assert "async function pollAnalysisTask(taskId)" in HTML
    assert "/api/analyze/status/" in HTML
    assert "response.status===202" in HTML


def test_carbon_display_discloses_proxy_method_and_validation():
    assert "activeAnalysis.carbonData=data.carbon_data||null" in HTML
    assert "estimated_total_co2e_kg" in HTML
    assert "AI材料质量估算" in HTML
    assert "DEFRA 2024参考因子" in HTML
    assert "材料质量（千克）× 对应排放因子" in HTML
    assert "不是实测碳排或完整生命周期评价" in HTML
    assert "不展示未经依据的减排百分比" in HTML
    assert "需工程验证" in HTML


def test_advanced_home_steps_require_a_successful_upload_analysis():
    assert 'id="uploadRequiredModal"' in HTML
    assert "请先上传包装" in HTML
    assert "完成包装上传与AI识别后，即可进入重设计与影响评估。" in HTML
    assert "function canAccessAdvancedSteps()" in HTML
    assert 'sourceMode==="upload"&&pendingFile&&latestAnalysisResult?.success===true&&latestAnalysisResult?.data' in HTML
    assert 'selector==="#prescription"||selector==="#impact"' in HTML
    assert "event.preventDefault();\n        event.stopPropagation();" in HTML
    assert 'document.getElementById("checkup").scrollIntoView({behavior:scrollBehavior,block:"start"})' in HTML
    assert 'event.key==="Escape"&&!uploadRequiredModal.hidden' in HTML
    assert 'if(event.target===uploadRequiredModal)closeUploadRequiredModal()' in HTML
    assert "latestAnalysisResult=null;\n        window.latestAnalysisResult=null;" in HTML


def test_scanner_uses_staged_eight_second_diagnostic_timeline():
    for marker in (
        'schedule(()=>workbenchCanvas.classList.add("scan-locate","timeline-scan"),500)',
        '"scan-outline-active"',
        '"scan-components-active"',
        'showMaterialClue(0)},2600)',
        'schedule(()=>showMaterialClue(1),3000)',
        'schedule(()=>showMaterialClue(2),3400)',
        'schedule(()=>scanner.classList.add("uncertainty-intro"),5300)',
        'schedule(()=>scanner.classList.add("confidence-visible"),6000)',
        '},8200)',
        '},8600)',
    ):
        assert marker in HTML
    assert "stroke-dasharray" in HTML
    assert "outlineDraw" in HTML
    assert "designerScan 2.5s linear" in HTML
    assert "analysisProgress 8.2s" in HTML
    assert "cubic-bezier(.22,1,.36,1)" in HTML
    assert 'id="analysisReplayButton"' in HTML
    assert "查看诊断结果" in HTML
