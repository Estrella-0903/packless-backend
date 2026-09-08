// Execute the actual frontend polling function without contacting a paid provider.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const html=fs.readFileSync(require('node:path').join(__dirname,'../frontend/index.html'),'utf8');
for(const match of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(match[1]);
const poll=html.slice(html.indexOf('async function pollImageTask('),html.indexOf('async function requestRedesign('));
const accessGuard=html.slice(html.indexOf('function canAccessAdvancedSteps()'),html.indexOf('function closeUploadRequiredModal()'));
function canAccess({sourceMode='upload',pendingFile=null,latestAnalysisResult=null}={}){
  const context=vm.createContext({sourceMode,pendingFile,latestAnalysisResult,Boolean});
  vm.runInContext(accessGuard,context);
  return vm.runInContext('canAccessAdvancedSteps()',context);
}
function renderScoreFixture(kind,data,score){
  const panel={innerHTML:''};
  const context=vm.createContext({
    document:{getElementById(id){assert.equal(id,'scoreDetails');return panel}},
    activeAnalysis:{scores:{[kind]:score},scoreBreakdown:{[kind]:data}},
    Number,String,Array,Math
  });
  const source=html.slice(html.indexOf('function renderScoreBreakdown('),html.indexOf('function animateNumber('));
  vm.runInContext(source,context);
  vm.runInContext(`renderScoreBreakdown(${JSON.stringify(kind)})`,context);
  return panel.innerHTML;
}
async function run(states){
  const calls=[];
  const context=vm.createContext({
    redesignRequestId:1,encodeURIComponent,console,AbortSignal,Error,
    setTimeout(fn,ms){assert.equal(ms,2500);fn()},
    async fetch(url){calls.push(url);return {ok:true,json:async()=>({success:true,data:states.shift()||{status:'PENDING'}})}}
  });
  vm.runInContext(poll,context);
  return {promise:vm.runInContext('pollImageTask("task-test",1)',context),calls,context};
}
(async()=>{
  let result=await run([{status:'PENDING'},{status:'RUNNING'},{status:'SUCCEEDED',optimized_image_url:'/generated/real.png'}]);
  assert.equal(await result.promise,'/generated/real.png');
  assert.equal(result.calls.length,3);
  assert(result.calls.every(url=>url==='/api/redesign/image-status/task-test'));
  result=await run([{status:'FAILED',error:'provider failed'}]);
  await assert.rejects(result.promise,/provider failed/);
  result=await run([]);
  await assert.rejects(result.promise,/等待超时/);
  assert.equal(result.calls.length,20);
  result=await run([{status:'SUCCEEDED'}]);
  await assert.rejects(result.promise,/未返回优化图片/);
  const replay=html.slice(html.indexOf('function startAnalysis()'),html.indexOf('fileInput.addEventListener'));
  assert(!replay.includes('requestRedesign('),'replay must never resubmit Wan');
  assert(!canAccess(),'first visit must remain locked');
  assert(!canAccess({pendingFile:{name:'package.png'}}),'selected file without analysis must remain locked');
  assert(!canAccess({pendingFile:{name:'package.png'},latestAnalysisResult:{success:false}}),'failed analysis must remain locked');
  assert(canAccess({pendingFile:{name:'package.png'},latestAnalysisResult:{success:true,data:{analysis_id:'test'}}}),'successful upload analysis must unlock advanced steps');
  assert(!replay.includes('latestAnalysisResult=null'),'replay must preserve advanced-step access');
  const heroClick=html.slice(html.indexOf('heroSteps.forEach(link=>link.addEventListener'),html.indexOf('document.getElementById("restartButton")'));
  assert(heroClick.indexOf('guardAdvancedStep(event,link)')<heroClick.indexOf('!net.classList.contains("ready")'),'03/04 guard must run even while the opening animation is active');
  assert(html.includes('animateComparison(100,50)'));
  const environment=renderScoreFixture('environment',{
    no_improvement_penalty:15,baseline_adjustment:4.5,
    items:[{title:'碳排改善',score:50,weight_percent:30,points:15,max_points:30,explanation:'参考碳排预计减少 5%。',source:'DEFRA 2024',requires_validation:true}]
  },45);
  assert.match(environment,/有效改善校正/);
  assert.match(environment,/−15/);
  assert.match(environment,/保守展示基线/);
  assert.match(environment,/建议工程验证/);
  const business=renderScoreFixture('business',{speculative_structural_penalty:12,items:[]},70);
  assert.match(business,/低置信度结构动作/);
  assert.match(business,/−12/);
  console.log('Frontend polling, step guard, score breakdown, replay and syntax checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
