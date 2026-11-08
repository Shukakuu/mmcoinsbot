'use strict';
// Text-only rendering of untrusted headlines and token metadata.
let strategyReport = null;
const strategyLabels = {blocked:'Bloqué',unverified:'Non vérifié',watch:'À surveiller',review:'À examiner manuellement'};
function renderV2(){
  if(!strategyReport)return;
  const out=document.getElementById('strategyRows');out.replaceChildren();
  const key=document.getElementById('strategyHorizon').value;
  const state=document.getElementById('strategyState').value;
  let rows=strategyReport.coins.map(c=>({...c,selected:c.strategies.find(s=>s.key===key)}));
  rows.sort((a,b)=>['review','watch','unverified','blocked'].indexOf(a.selected.state)-['review','watch','unverified','blocked'].indexOf(b.selected.state));
  if(state!=='all')rows=rows.filter(c=>c.selected.state===state);
  for(const c of rows.slice(0,60)){
    const card=element('article','field');
    const button=element('button','row-action',(c.symbol||'?')+' · '+strategyLabels[c.selected.state]);
    button.addEventListener('click',()=>openDetail(c.mint));card.append(button);
    card.append(element('p','', [...c.risk.blockers,...c.risk.unknown,...c.selected.reasons].join(' · ')||'Critères observés réunis. Vérification manuelle nécessaire.'));
    for(const ev of c.events.slice(0,3)){
      const line=element('p','sub-note',(ev.relation==='contract_mention'?'Mention du contrat':'Hypothèse thématique')+' · '+ev.source+' · '+ev.title);
      if(ev.url){const a=element('a','plain-link',' Source ↗');a.href=ev.url;a.target='_blank';a.rel='noopener noreferrer';line.append(a);}card.append(line);
    }
    out.append(card);
  }
  if(!rows.length)out.append(element('p','empty-small','Aucun token pour ce filtre.'));
  document.getElementById('strategyNote').textContent=(strategyReport.demo?'DÉMO FICTIVE · ':'')+strategyReport.note;
  const news=document.getElementById('worldNews');news.replaceChildren();
  const statuses=strategyReport.news_status.sources||{};
  document.getElementById('worldHealth').textContent=Object.entries(statuses).map(([name,s])=>name+' : '+(s.error?'indisponible ('+s.error+')':s.items+' titres')+' · dernier succès '+ago(s.last_success)).join(' | ')||'Aucune source active en démo / en attente du premier relevé.';
  for(const e of strategyReport.events.slice(0,12)){
    const row=element('p','',e.source+' · '+ago(e.published_at)+' · ');
    if(e.url){const a=element('a','plain-link',e.title);a.href=e.url;a.target='_blank';a.rel='noopener noreferrer';row.append(a);}else row.append(document.createTextNode(e.title));news.append(row);
  }
  if(!strategyReport.events.length)news.textContent='Aucun événement récent reçu.';
  const calendar=document.getElementById('upcomingEvents');calendar.replaceChildren();
  for(const e of strategyReport.upcoming||[])calendar.append(element('p','',e.date+' · '+e.title+' · '+e.source+' · à confirmer'));
  if(!calendar.childNodes.length)calendar.textContent='Aucune date future explicite reçue.';
  const narratives=document.getElementById('emergingNarratives');narratives.replaceChildren();
  for(const n of strategyReport.narratives.slice(0,12))narratives.append(element('p','',n.term+' · '+({acceleration:'Accélération',appearance:'Apparition',decline:'Essoufflement',persistent:'Persistance'}[n.phase]||'Hypothèse')+' · '+n.current+' mentions cette heure / '+n.previous+' heure précédente · '+n.sources.length+' sources'));
  if(!strategyReport.narratives.length)narratives.textContent='Pas encore assez de publications récentes.';
}
async function refreshV2(){try{strategyReport=await get('/api/v2');renderV2();}catch(e){document.getElementById('worldHealth').textContent='Veille V2 indisponible : '+e.message;}}
document.getElementById('strategyHorizon').addEventListener('change',renderV2);
document.getElementById('strategyState').addEventListener('change',renderV2);
poll(refreshV2,15000);
