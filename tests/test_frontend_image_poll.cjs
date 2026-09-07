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
  assert(html.includes('animateComparison(100,50)'));
  console.log('Frontend polling and step guard: success, failure, timeout, access states, replay and syntax checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
