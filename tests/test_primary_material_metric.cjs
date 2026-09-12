const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../frontend/index.html'),'utf8');
const source=html.slice(
  html.indexOf('function buildPrimaryMaterialMetric('),
  html.indexOf('function renderPrimaryMaterialMetric(')
);
const context=vm.createContext({Number,String,Array,Set,Math});
vm.runInContext(source,context);
const metric=(analysis,redesign)=>vm.runInContext(
  `buildPrimaryMaterialMetric(${JSON.stringify(analysis)},${JSON.stringify(redesign)})`,
  context
);

const plastic=metric(
  {data:{packaging:{materials:[{component:'PET plastic tray',material:'PET'}]}}},
  {data:{before:{plastic_weight_g:28},after:{plastic_weight_g:6},options:[{id:'balanced',selected_rule_ids:['R03']}],recommended_option:'balanced'}}
);
assert.equal(plastic.label,'塑料使用');
assert.equal(plastic.before,28);
assert.equal(plastic.after,6);
assert.equal(plastic.unit,'克');

const recognizedPlasticWithoutWeight=metric(
  {data:{packaging:{materials:[{component:'plastic film',material:'unknown'}]}}},
  {data:{before:{plastic_weight_g:0},after:{plastic_weight_g:0},options:[{id:'balanced',selected_rule_ids:['R03']}],recommended_option:'balanced'}}
);
assert.equal(recognizedPlasticWithoutWeight.label,'塑料使用');
assert.equal(recognizedPlasticWithoutWeight.before,'存在');
assert.equal(recognizedPlasticWithoutWeight.after,'减少');
assert.equal(recognizedPlasticWithoutWeight.unit,'');

const multiMaterial=metric(
  {data:{packaging:{materials:[
    {component:'lid',material:'paperboard'},
    {component:'base',material:'cardboard'},
    {component:'wrap',material:'coated paper'},
    {component:'insert',material:'molded pulp'},
    {component:'uncertain lining',material:'unknown'}
  ]}}},
  {data:{before:{},after:{packaging_state:{components:[
    {material:'paperboard'},{material:'molded pulp'}
  ]}}}}
);
assert.equal(multiMaterial.label,'材料种类');
assert.equal(multiMaterial.before,3,'paperboard/cardboard duplicates and unknown must not inflate the count');
assert.equal(multiMaterial.after,2);
assert.equal(multiMaterial.unit,'种');

const complexity=metric(
  {data:{packaging:{materials:[{component:'box',material:'paperboard'}]}}},
  {data:{opportunities:[{rule_id:'R04',action:'simplify_materials'}]}}
);
assert.deepEqual(
  JSON.parse(JSON.stringify(complexity)),
  {label:'材料复杂度',before:'中等',after:'低',unit:'',status:'inferred',source:'规则估算'}
);

const paper=metric(
  {data:{packaging:{materials:[
    {component:'lid',material:'paperboard'},
    {component:'base',material:'paperboard'}
  ]}}},
  {data:{
    before:{packaging_state:{components:[
      {material:'paperboard',material_family:'paper',estimated_weight_g:70},
      {material:'paperboard',material_family:'paper',estimated_weight_g:56}
    ]}},
    after:{packaging_state:{components:[
      {material:'paperboard',material_family:'paper',estimated_weight_g:60},
      {material:'paperboard',material_family:'paper',estimated_weight_g:44}
    ]}}
  }}
);
assert.equal(paper.label,'纸材用量');
assert.equal(paper.before,126);
assert.equal(paper.after,104);
assert.equal(paper.source,'包装数字模型');

const fallback=metric(
  {data:{packaging:{materials:[{component:'lining',material:'unknown'}]}}},
  {data:{before:{plastic_weight_g:0},after:{plastic_weight_g:0}}}
);
assert.equal(fallback.label,'材料结构');
assert.equal(fallback.before,'暂无法判断');
assert.notEqual(fallback.label,'塑料使用');

assert.match(html,/id="materialMetricLabel"/);
assert.doesNotMatch(html,/<small>塑料使用<\/small><div class="metric-values"><b data-before-metric="plasticWeight"/);
console.log('Dynamic primary material metric cases passed.');
