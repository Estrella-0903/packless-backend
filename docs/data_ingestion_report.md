# 智减数据接入审计报告

本次为离线数据层接入，不训练模型、不向提示词注入数据集、不改变前端与 Wan 图片生成。未推送 Git 或部署 Render。

## 1. C 数据实际内容

`c_results_all.json` 是 **50 条**对象组成的数组，不是约 300 条。
`c_results.zip` 包含 50 个 JSON；按图片文件名逐条比对，50 条全部与汇总记录相同，因此不追加计数。
标准化 JSON 与 CSV 各 50 条，一张图片对应一条，原数据完整保留在 `raw_fields`。

|字段|类型|缺失率|空值/空列表率|
|---|---|---|---|
|source_file|string|0%|0%|
|analysis|object|0%|0%|
|analysis.package_type|string|0%|0%|
|analysis.materials|array|0%|0%|
|analysis.components|array|0%|2%|
|analysis.issues|array|0%|100%|

`package_type` 实际表示产品用途类别，并非瓶、盒等包装形态。
类别为 beverage 28、food 7、personal care 5、cleaning products 1、unknown 9。
材料出现次数：plastic 30、metal 14、glass 7、cardboard 3、aluminum 2、plastic film 1、paperboard 1；一条记录可含多种材料，不能相加当作样本数。

没有 confidence、source dataset、原始 TACO category ID/label 或独立 prediction 字段。
`analysis` 按用户描述视为识别结果；`source_dataset=TACO` 仅来自用户说明，附 `source_attribution`，未独立验证数据集成员身份。
这些数据不是人工标注真值，不能据此声称识别准确率或校准模型置信度。

## 2. 标签映射与覆盖率

`data/mappings/packaging_taxonomy.json` 是可维护的词法映射配置，支持用户要求的 15 个标准类别。
保留原始组件标签、全部映射类别、映射来源和映射置信度。0.7 是保守的人工映射启发值，不是测得的识别概率；原始识别 `confidence` 全部为 null。

- 非 unknown 图像级映射：49/50 = **98%**。
- 已配置组件标签出现次数：99/99 = **100%**。
- 最终类别：other_packaging 41、metal_can 5、plastic_bottle 1、plastic_tray 1、carton 1、unknown 1。
- 98% 包含 other_packaging，不代表 98% 已精细分类或正确识别。具体类别只有 8/50；41 条仍为宽泛包装类。

多组件保留 `mapped_categories`，不强行选出未经确认的主包装材质；materials 与 components 数组不能按索引配对。
多种材料并存不等于复合层压材料。仅有 bottle 不默认 PET，仅有 outer box 不默认纸板。
多个材料的图像级 material_family/subtype 保留 unknown，原数组不丢失。

## 3. PackWISE

ZIP 元数据审计：23 类、586 张图、6,713 个实例标注。

|划分|图片|实例|
|---|---:|---:|
|train|410|4,669|
|val|88|990|
|test|88|1,054|

压缩包 README 描述为输送带上的消费后包装废弃物 COCO 实例分割数据，声明 CC BY 4.0，2025 年，贡献者 L. Roming、S. Rueger、M. Kalb、F. Beutler。此为文件内声明，未额外核验线上许可证。
本阶段仅保存分割计数、原始类别与 README 到 `packwise_metadata.json`；**没有把 6,713 个实例伪装成 586 条材料识别结果，也未训练或复制大图**。
分类映射已覆盖其标签词汇，undefined/wood/textile 等仍保留 unknown，不能单凭名称认定非包装或具体树脂。

## 4. DEFRA 提取与边界

来源：用户提供的 UK Government DEFRA 2024 Greenhouse Gas Conversion Factors，Condensed set v1.1，工作表 `Material use`。
脚本检查年份、版本、单位和列标题。D 列为 Primary material production，G 列为 Closed-loop source。
提取 **9 类材料 × 2 种来源 = 18 条因子**，每条保存工作簿名、SHA-256、工作表、单元格、原始标签和值、材料来源及核验范围。

|标准材料|D列单元格|原值 kg CO2e/tonne|换算 kg CO2e/kg|
|---|---|---:|---:|
|plastic_film|D73|2910.46529|2.91046529|
|hdpe|D75|3086.39038|3.08639038|
|ldpe_lldpe|D76|2959.31834|2.95931834|
|pet_plastic|D77|3854.91851|3.85491851|
|pp|D78|2568.58892|2.56858892|
|ps|D79|4367.44048|4.36744048|
|pvc|D80|2935.77335|2.93577335|
|paperboard|D85|1193.96586|1.19396586|
|paper|D87|1339.31834|1.33931834|

统一除以 1000；禁止再次除以 1000。G 列单独保存，不混入 D 列。例如 PET 闭环来源为 2.20491851 kg CO2e/kg。
`verified=true` 只表示与提供的表格及单位一致，不表示已验证当前包装材质。
这些因子为采购材料的 cradle-to-gate 参考，非包装完整生命周期、非回收评分、非废弃处置因子，不能直接推算减少塑料的净环境收益。
默认查询原生来源是**场景假设**，返回 `origin_requires_confirmation=true`，不能当作实际再生比例。
塑料薄膜为平均薄膜因子；LDPE/LLDPE 是合并类别，不是某个供应商的精确生产数据。

## 5. 材料匹配

- exact：PET / PET plastic / polyethylene terephthalate、paperboard / cardboard、plastic film、HDPE、LDPE、LLDPE、PP / polypropylene、PS、PVC、paper，以及已配置标准名。
- inferred：plastic bottle（不能判定 PET）、paper box（可能有涂层或复合结构）。两者返回 null 因子并要求验证。
- unknown：generic plastic、metal、glass、aluminum、molded pulp、recycled PET 等本阶段未有适配的具体别名/边界；不冒用近似材料。
- C 样本中的明确纸板和薄膜可以查参考因子；C 文件没有明确 PET 标签，因此不能宣称已从这些预测中识别出 PET。

exact/confidence=1.0 是**名称匹配置信度**，不是图片识别置信度。API 材料引用单独保留 identification_confidence 并要求验证。
缺失/损坏映射或因子文件、安全检查失败、重复因子，均退为不可用/null，不阻断原分析与图片链路。

## 6. 当前接入点与仍然固定的评分

`/api/analyze` 在 Qwen 结果校验后由服务器计算可选 `carbon_data`；`create_redesign_plan` 重新查询本地数据，不信任客户端旧 carbon_data。
既有字段、接口路径、评分算法、图片生成保持不变。旧前端可以忽略新增字段。

**真正来自数据的部分**：材料参考因子、材料来源类别、单位换算、逐材料碳排参考计算及其来源追踪。
**没有转成实测的部分**：环境数值分仍为 `45 + Σ(规则固定权值 × confidence)`，R01–R05 权值仍为 14/16/18/12/9；商业/供应链罚分仍是 low=2、medium=6、high=14，验证罚分 2；综合权重仍为 0.4/0.3/0.3。
这些属于规则启发评分，不是 DEFRA 校准分数。`environment_score_basis` 明确披露这一点；缺少前后 BOM/重量，不能用因子数值直接给减量方案加分或宣称减碳。
`/api/materials` 的原演示库 `co2_factor` 和回收评分没有替换，避免本次扩大范围；其值**不等于**新增 DEFRA 引用，不能混用。
原 `environmental_impact` 保持兼容，来源仍是分析输出；不得将其图片估计重量误当作实测输入。

## 7. 重量与计算

仅名称匹配时：factor_available=true，但 estimated_total_co2e_kg=null，requires_weight_measurement=true。
服务函数 `calculate_material_carbon("PET", 0.1)` 得到 0.385491851 kg CO2e 的参考估计。质量单位必须为 kg，来源假设仍需确认。

现有 JSON `/api/redesign` 可在 `packaging.materials` 中附明确数据，例如：

```json
{
  "packaging": {
    "bill_of_materials_complete": true,
    "materials": [{
      "component": "tray", "material": "PET", "confidence": 1.0,
      "weight_kg": 0.1, "weight_source": "measured",
      "material_verified": true,
      "material_origin": "primary_material_production"
    }]
  }
}
```

这些是调用方显式声明，不是实验室验证机制。无需更改已有必填参数，也不增加前端输入 UI。
只有 material_verified=true 且 weight_source 为 measured/user_supplied 时接收逐材料重量；负数、布尔值、NaN、Infinity、字符串、未知重量均不计算。
只有明确完整 BOM 且每个材料均有可用质量和因子，才汇总包装总量。未知材料不当零排放，不能把总包装质量重复乘到每种材料上。
缺完整 BOM 仍可返回逐材料参考小计，但总量保持 null。未声明材料来源时按原生情景估计并标记待确认。

`D_basic_calculation_result.json` 是一条化妆品包装的示例计算，不是材料因子集或当前用户包装实测值。原始体积 3000、改后 2093 cm³、减重 0.015 kg/件及年节材 1500 kg 是其中输入对应的算术结果，未注入业务默认值。
待补充：逐组件称重、聚合物/涂层确认、再生成分比例、前后尺寸与完整 BOM、年用量、供应商工艺及地区数据、运输与保护测试。重量和体积不同，不能以缩小 20% 图片尺寸推定减重 20%。

## 8. 复现、测试和部署

离线依赖放在 `requirements-data.txt`；运行时 requirements.txt 无需新增依赖。

```powershell
python -m pip install -r requirements-data.txt
python scripts/ingest_material_data.py --source-dir 'C:\Users\ASUS\Desktop\清华'
python -m pytest -q
```

原始小文件只复制到被 Git 忽略的 `data/raw`，不覆盖内容不同的已有快照。大 ZIP 原位审计；来源文件名、字节数与 SHA-256 写入 source_manifest.json。结构化 JSON/CSV、映射、代码和文档应随应用部署，运行时不依赖桌面路径或 Excel。
测试覆盖 exact、unknown、ambiguous、两类来源/单位、未知及非法重量、实测乘法、混合材料 BOM、损坏映射/因子、缺文件、API 新字段及老页面端点。Qwen/Wan 在回归测试中使用隔离桩，不产生付费请求；这不是一次线上模型效果评估。

本次执行结果：**58 passed**。另有 DashScope 与 Starlette/httpx 的 2 条弃用警告，无测试失败。

新增文件：`app/services/material_data_service.py`、`scripts/ingest_material_data.py`、`tests/test_material_data_service.py`、`requirements-data.txt`、本报告、`data/raw/README.md`；映射目录下的 `packaging_taxonomy.json`、`material_factor_mapping.json`、`defra_materials.json`；processed 下的 `taco_normalized.json/.csv`、`defra_emission_factors.json/.csv`、`packwise_metadata.json`、`source_manifest.json`、`ingestion_audit.json`。
修改文件：`.gitignore`、`app/routers/analyze.py`、`app/services/redesign_service.py`、`app/schemas/models.py`。

建议下一步优先接入**人工确认的逐组件 BOM 和前后实测重量**，随后是地区/供应商相关的再生成分与工艺因子。比继续添加未核验图片预测，更能支持可信的方案减碳比较。
