'use strict';
const names={Nagi:'Nagi-HUGE',Laya:'Laya',SemIf:'OpenJev / SemIf',Jev:'Jev'};
const order=['Nagi','Laya','SemIf','Jev'];
const pct=x=>x==null?'—':(100*x).toFixed(2)+'%';
const signed=x=>(x>=0?'+':'')+(100*x).toFixed(2);
let data,track='common';
function render(){
 const body=document.querySelector('#leaderboard tbody');body.replaceChildren();
 for(const key of order){const m=data.models[key],tr=document.createElement('tr');if(key==='Nagi')tr.className='nagi';
 const vals=[`<a href="${m.url}">${names[key]} ↗</a><span class="sub">${m.subtitle}</span>`,`<span class="accuracy">${pct(m[track].accuracy)}</span>`,`${m.valid.toLocaleString()} / 4,671`,m.untruncated==null?'Unknown (API)':`${m.untruncated.toLocaleString()} / 4,671`,m.flip_display];
 for(const val of vals){const td=document.createElement('td');td.innerHTML=val;tr.append(td);}body.append(tr);}
 document.querySelector('#track-note').textContent=track==='common'?'4,518 original examples · eight equal source weights · all local inputs intact · API failures retained':'4,671 original examples · native truncation retained · unsupported/invalid/missing outputs count wrong';
 for(const b of document.querySelectorAll('[data-track]')){const active=b.dataset.track===track;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));}
 renderBars();
}
function renderBars(){
 const source=document.querySelector('#source').value,chart=document.querySelector('#source-chart');chart.replaceChildren();
 for(const key of order){const value=source==='all'?data.models[key][track].accuracy:data.models[key][track].sources[source];const row=document.createElement('div');row.className='bar-row'+(key==='Nagi'?' nagi':'');const label=document.createElement('span');label.textContent=names[key];const base=document.createElement('div');base.className='bar-track';const bar=document.createElement('div');bar.className='bar-fill';bar.style.width=(100*(value||0))+'%';base.append(bar);const n=document.createElement('b');n.textContent=pct(value);row.append(label,base,n);chart.append(row);}
}
function latency(target,items){const el=document.querySelector(target);for(const [name,p50,p95] of items){const row=document.createElement('div');row.className='latency-row';const label=document.createElement('span');label.textContent=name;const value=document.createElement('span');value.textContent=`${Math.round(p50)} / ${Math.round(p95)} ms`;row.append(label,value);el.append(row);}const note=document.createElement('p');note.className='small';note.textContent='P50 / P95 · observed request distribution';el.append(note);}
fetch('data.json').then(r=>{if(!r.ok)throw Error('Result artifact unavailable');return r.json();}).then(d=>{data=d;
 for(const source of data.sources){const option=document.createElement('option');option.value=source;option.textContent=source.toUpperCase();document.querySelector('#source').append(option);}
 document.querySelector('#source').addEventListener('change',renderBars);for(const b of document.querySelectorAll('[data-track]'))b.addEventListener('click',()=>{track=b.dataset.track;render();});
 document.querySelector('#finding p').textContent=data.finding;
 for(const c of data.comparisons){const row=document.createElement('div');row.className='interval';const h=document.createElement('strong');h.textContent=`Nagi − ${names[c.reference]}: ${signed(c.difference)} pp`;const ci=document.createElement('span');ci.textContent=`95% interval [${signed(c.ci95[0])}, ${signed(c.ci95[1])}]`;const adj=document.createElement('span');adj.textContent=`Adjusted interval [${signed(c.adjusted[0])}, ${signed(c.adjusted[1])}]`;row.append(h,ci,adj);document.querySelector('#intervals').append(row);}
 latency('#local-latency',order.filter(k=>k!=='Jev').map(k=>[names[k],data.models[k].latency.p50_ms,data.models[k].latency.p95_ms]));latency('#jev-latency',[['Jev API',data.models.Jev.latency.p50_ms,data.models.Jev.latency.p95_ms]]);
 document.querySelector('#version').textContent='Evaluation: 24 September 2026 · data SHA '+data.analysis_sha256.slice(0,12);render();
}).catch(error=>{document.querySelector('#track-note').textContent='The results could not be loaded. Please use the linked report and raw receipts.';console.error(error);});
