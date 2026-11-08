// Panneau « Surlignages J7 » : lecture seule, aucune action de trading.
(()=>{
 const $=id=>document.getElementById(id);
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const MINT=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
 const statuses={a_etudier:'À étudier',surveillance:'Surveillance',incomplet:'Incomplet',risque:'Risque',expire:'Périmé'};
 let demo=false,last='';
 const age=s=>s<90?Math.round(s)+' s':s<5400?Math.round(s/60)+' min':(s/3600).toFixed(1)+' h';
 const pct=v=>v==null?'—':`<span class="${v>0?'up':v<0?'down':''}">${v>0?'+':''}${Number(v).toFixed(1)} %</span>`;
 const lat=v=>v==null?'—':(v<10?Number(v).toFixed(1):Math.round(v))+' s';
 const med=(v,n,ok)=>v==null?'—':pct(v)+` <small class="tiny">n=${n}${ok?'':' · non concluant'}</small>`;
 function label(r){
  const via=r.via.startsWith('launch_card:')?'carte '+r.via.slice(12):({token_meta:'surlignage panneau',post_ca:'CA dans le post',external_ca:'CA hors X'}[r.via]||r.via);
  return esc(via)+(r.platform&&r.platform!=='X'?` <small class="tiny">${esc(r.platform)}</small>`:'')+(r.flags&&r.flags.isContractLaunch?' <small class="tiny" title="Drapeau envoyé par J7, sens non vérifié">drapeau lancement</small>':'');
 }
 function row(r){
  const mint=r.mint,short=mint.slice(0,4)+'…'+mint.slice(-4);
  const axiom=!demo&&MINT.test(mint)?`<a class="axiom-inline" href="https://axiom.trade/meme/${encodeURIComponent(mint)}?chain=sol" target="_blank" rel="noopener noreferrer">AXIOM ↗</a>`:'';
  const name=(r.symbol?'$'+esc(r.symbol):'$?')+(r.name?` <small class="tiny">${esc(r.name.slice(0,18))}</small>`:'');
  return `<tr><td>${age(r.age_s)}</td><td>${label(r)}</td>
   <td>${r.author?'@'+esc(r.author):'<span class="tiny">inconnu</span>'}${r.followers!=null?` <small class="tiny">${Intl.NumberFormat('fr-FR',{notation:'compact'}).format(r.followers)}</small>`:''}</td>
   <td>${name}<br><code class="j7-mint" data-copy="${esc(mint)}" title="Cliquer pour copier">${esc(short)}</code> ${axiom}</td>
   <td>${r.status?`<span class="pill ${esc(r.status)}">${esc(statuses[r.status]||r.status)}</span>`:'<span class="tiny">pas encore analysé</span>'}</td>
   <td>${lat(r.latency_s)}</td><td>${r.quoted_lag_s==null?'<span class="tiny">aucune</span>':lat(r.quoted_lag_s)}</td>
   <td>${pct(r.outcomes['60'])}</td><td>${pct(r.outcomes['300'])}</td><td>${pct(r.outcomes['1200'])}</td></tr>`;
 }
 function stats(items){
  return items.length?items.map(e=>`<tr><td>${esc(e.key)}</td><td>${e.n}</td><td>${lat(e.latency_median_s)}</td><td>${e.quoted}/${e.n}</td>
   <td>${med(e.ret_300_median,e.ret_300_n,e.ret_300_conclusive)}</td><td>${med(e.ret_1200_median,e.ret_1200_n,e.ret_1200_conclusive)}</td></tr>`).join(''):'<tr><td colspan="6" class="muted">Pas encore de données.</td></tr>';
 }
 function render(d){
  demo=!!d.demo;
  const t=d.totals||{},s=d.status||{};
  $('j7Summary').textContent=demo?'Mode démo : aucune donnée J7 réelle.':
   `J7 ${s.connected?'connecté':'non connecté'} · ${t.highlights_7d??0} surlignage(s) sur 7 j · latence médiane ${lat(t.latency_median_s)} · ${t.never_quoted??0} jamais coté(s)`;
  const key=JSON.stringify([d.recent,d.authors,d.vias,s.connected]);
  if(key===last)return;last=key;
  $('j7Rows').innerHTML=(d.recent||[]).length?d.recent.map(row).join(''):
   '<tr><td colspan="10" class="muted">Aucun surlignage reçu pour l’instant. Sans jeton J7 valide ou sans compte suivi, ce panneau reste vide.</td></tr>';
  $('j7Authors').innerHTML=stats(d.authors||[]);
  $('j7Vias').innerHTML=stats(d.vias||[]);
  $('j7Note').textContent=d.note||'';
  const sc=(d.schemas||[]).slice(0,8).map(x=>x.kind+' : '+x.keys.slice(0,18).join(', ')).join(' | ');
  $('j7Schemas').textContent=sc?'Champs réellement envoyés par J7 (clés seulement) — '+sc:'';
 }
 document.addEventListener('click',e=>{
  const el=e.target.closest&&e.target.closest('[data-copy]');
  if(el&&navigator.clipboard)navigator.clipboard.writeText(el.dataset.copy).then(()=>{const o=el.textContent;el.textContent='copié ✓';setTimeout(()=>el.textContent=o,900)}).catch(()=>{});
 });
 async function tick(){
  try{const r=await fetch('/api/j7',{cache:'no-store'});if(r.ok)render(await r.json());}catch{}
 }
 tick();setInterval(tick,3000);
})();
