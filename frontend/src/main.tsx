import React,{useEffect,useState} from 'react';
import{createRoot}from'react-dom/client';
import './style.css';
type Job={id:string;name:string;status:string;logs:string;exit_code:number|null;duration_ms:number|null};
type Run={id:string;pipeline_id:string;fixture:string;status:string;triggered_at:string;jobs:Job[];failure_reason:string|null};
type Pipeline={id:string;name:string;steps:{name:string;command:string}[]};
type View='dashboard'|'pipelines'|'history';
const BASE=import.meta.env.VITE_API_URL || '';
async function api(path:string,method='GET',body?:unknown){
 const res=await fetch(`${BASE}${path}`,{method,headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
 const text=await res.text();
 if(!res.ok){
  throw new Error(text ? text.slice(0,200) : `Request failed (${res.status})`);
 }
 if(!text){
  return null;
 }
 try{return JSON.parse(text);}catch(error){
  throw new Error(`Invalid JSON response from ${path}: ${text.slice(0,200)}`);
 }
}
function App(){
 const[pipelines,setPipelines]=useState<Pipeline[]>([]),[runs,setRuns]=useState<Run[]>([]),[selected,setSelected]=useState<string|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const[view,setView]=useState<View>('dashboard');
 async function refresh(){try{const[p,r]=await Promise.all([api('/api/pipelines'),api('/api/runs')]);setPipelines(p);setRuns(r);setError('');}catch(e){setError(String(e));}}
 useEffect(()=>{refresh();const t=setInterval(refresh,2000);return()=>clearInterval(t)},[]);
 async function trigger(fixture='success'){if(!pipelines[0])return;setBusy(true);try{const r=await api(`/api/pipelines/${pipelines[0].id}/runs`,'POST',{fixture});setSelected(r.id);await refresh()}catch(e){setError(String(e))}finally{setBusy(false)}}
 async function action(id:string,kind:'cancel'|'rerun'){setBusy(true);try{const r=await api(`/api/runs/${id}/${kind}`,'POST');if(kind==='rerun')setSelected(r.id);await refresh()}catch(e){setError(String(e))}finally{setBusy(false)}}
 const current=runs.find(r=>r.id===selected)||runs[0],passed=runs.filter(r=>r.status==='passed').length,failed=runs.filter(r=>r.status==='failed').length;
 const navigation: {id:View;label:string;icon:string}[]=[
  {id:'dashboard',label:'Dashboard',icon:'◈'},
  {id:'pipelines',label:'Pipelines',icon:'▤'},
  {id:'history',label:'Run history',icon:'◷'},
 ];
 return <div className="shell">
  <aside>
   <h1>⚡ MiniCI</h1>
   <p>Developer tools</p>
   <nav aria-label="Main navigation">
    {navigation.map(item=><button key={item.id} type="button" className={`nav-item ${view===item.id?'active':''}`} aria-current={view===item.id?'page':undefined} onClick={()=>setView(item.id)}><span aria-hidden="true">{item.icon}</span> {item.label}</button>)}
   </nav>
   <small>Local CI workspace</small>
  </aside>
  <main>
   <header>
    <div><span className="eyebrow">WORKSPACE / OVERVIEW</span><h2>{navigation.find(item=>item.id===view)?.label}</h2><p>Run, monitor and inspect your continuous integration workflow.</p></div>
    <div className="buttons"><button onClick={()=>trigger()} disabled={busy||!pipelines.length}>▶ Run pipeline</button><button className="secondary" onClick={()=>trigger('failure')} disabled={busy||!pipelines.length}>Failure demo</button></div>
   </header>
   {error&&<div className="error">{error}</div>}
   {view==='dashboard'&&<section className="metrics">
    <article><span>Total runs</span><strong>{runs.length}</strong></article>
    <article><span>Passed</span><strong>{passed}</strong></article>
    <article><span>Failed</span><strong>{failed}</strong></article>
    <article><span>Success rate</span><strong>{runs.length?Math.round(100*passed/runs.length):0}%</strong></article>
   </section>}
   {(view==='dashboard'||view==='pipelines')&&<section className="panel">
    <div className="panelhead"><h3>Pipeline configuration</h3><span className="pill">Predefined fixture</span></div>
    <p>{pipelines[0]?.name||'Loading...'} · Sample TypeScript</p>
    <div className="steps">{(pipelines[0]?.steps||[]).map((step,index)=><div key={step.name} className="step"><b>0{index+1} · {step.name}</b><code>{step.command}</code></div>)}</div>
   </section>}
   {(view==='dashboard'||view==='history')&&<>
    <section className="panel">
     <div className="panelhead"><h3>Recent runs</h3><span>{runs.length} displayed</span></div>
     {runs.length===0?<p>No runs yet. Start your first pipeline.</p>:<div className="history">{runs.map(run=><button key={run.id} className={'run '+(current?.id===run.id?'active':'')} onClick={()=>setSelected(run.id)}><code>#{run.id.slice(0,8)}</code><span>{run.fixture}</span><span className={'status '+run.status}>{run.status}</span><time>{new Date(run.triggered_at).toLocaleString()}</time></button>)}</div>}
    </section>
    {current&&<section className="panel">
     <div className="panelhead"><div><h3>Run #{current.id.slice(0,8)}</h3><p>{current.failure_reason||'Actual execution output and job status'}</p></div><div className="buttons">{['queued','running'].includes(current.status)?<button className="secondary" disabled={busy} onClick={()=>action(current.id,'cancel')}>Cancel</button>:<button className="secondary" disabled={busy} onClick={()=>action(current.id,'rerun')}>Rerun</button>}<span className={'status '+current.status}>{current.status}</span></div></div>
     <div className="steps">{current.jobs.map(job=><div className="step" key={job.id}><b>{job.name}</b><span className={'status '+job.status}>{job.status}</span><small>{job.duration_ms!==null?`${(job.duration_ms/1000).toFixed(1)}s`:''} {job.exit_code!==null?`· exit ${job.exit_code}`:''}</small></div>)}</div>
     {current.jobs.map(job=><details key={job.id} open={job.status==='failed'}><summary>{job.name} logs · {job.status}</summary><pre>{job.logs||'Waiting for output...'}</pre></details>)}
    </section>}
   </>}
  </main>
 </div>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
