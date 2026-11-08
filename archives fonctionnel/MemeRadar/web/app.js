'use strict';
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statuses={expire:['PÉRIMÉ','expire'],a_etudier:['À ÉTUDIER','a_etudier'],surveillance:['SURVEILLANCE','surveillance'],incomplet:['INCOMPLET','incomplet'],risque:['RISQUE','risque']};
let current={coins:[],stats:{},status:{}}, selected=null;
let connectionOk=false, lastDataAt=0, refreshInFlight=false, manualPendingUntil=0;
let noticeText='', noticeUntil=0;
let favorites=new Set();try{favorites=new Set(JSON.parse(localStorage.getItem('radar_favorites')||'[]'))}catch{}
// UI-only filters: never change discovery, backend scoring or historical storage.
const QUALITY_KEY='memeradar_quality_filters_v64';
const quality={score:40,hideRisks:true,hideStale:true,signalsOnly:false,coverage:0};
try{
 const persisted=JSON.parse(localStorage.getItem(QUALITY_KEY)||'{}');
 if(Number.isInteger(persisted.score)&&persisted.score>=0&&persisted.score<=90&&persisted.score%5===0)quality.score=persisted.score;
 if(typeof persisted.hideRisks==='boolean')quality.hideRisks=persisted.hideRisks;
 if(typeof persisted.hideStale==='boolean')quality.hideStale=persisted.hideStale;
 if(typeof persisted.signalsOnly==='boolean')quality.signalsOnly=persisted.signalsOnly;
 if([0,50,70,90].includes(persisted.coverage))quality.coverage=persisted.coverage;
}catch{}
function saveQuality(){try{localStorage.setItem(QUALITY_KEY,JSON.stringify(quality));}catch{}}
function syncQualityControls(){
 $('minimumScore').value=String(quality.score);
 $('hideRisks').checked=quality.hideRisks;
 $('hideStale').checked=quality.hideStale;
 $('withSignalsOnly').checked=quality.signalsOnly;
 $('minimumCoverage').value=String(quality.coverage);
 $('scoreThreshold').textContent=quality.score===0?'Tous les scores':`Score > ${quality.score}/100`;
 $('minimumScore').style.setProperty('--range-fill',String(quality.score/90*100)+'%');
}
// Pure predicate used by the renderer and regression tests.
function qualityPasses(c){
 const score=Number(c.score);
 if(!Number.isFinite(score)||(quality.score>0&&score<=quality.score))return false;
 if(quality.hideStale&&c.fresh===false)return false;
 if(quality.hideRisks&&c.status==='risque')return false;
 if(quality.signalsOnly&&!(c.patterns||[]).length)return false;
 if(quality.coverage>0&&Number(c.coverage||0)<quality.coverage)return false;
 return true;
}
function money(v){if(v===null||v===undefined||!Number.isFinite(Number(v)))return '—';const n=Number(v);return '$'+(Math.abs(n)>=1000?new Intl.NumberFormat('fr-FR',{maximumFractionDigits:0}).format(n):n.toLocaleString('fr-FR',{maximumFractionDigits:2}));}
function price(v){if(v===null||v===undefined||!Number.isFinite(Number(v))||v<=0)return '—';return '$'+(v<0.0001?Number(v).toPrecision(5):Number(v).toLocaleString('en-US',{maximumSignificantDigits:6}));}
function pct(v){return v===null||v===undefined?'—':`${v>0?'+':''}${Number(v).toFixed(1)} %`;}
function color(v){return v===null||v===undefined?'':v>=0?'up':'down';}
function age(v){return v===null||v===undefined?'—':v<60?Math.round(v)+' min':(v/60).toFixed(1)+' h';}
function since(ts){if(!ts)return 'Jamais';const sec=Math.max(0,Math.round(Date.now()/1000-ts));return sec<60?`${sec} s`:sec<3600?`${Math.round(sec/60)} min`:`${(sec/3600).toFixed(1)} h`;}
function shortMint(m){return m?esc(m.slice(0,5)+'…'+m.slice(-5)):'—';}
function coinId(c){return c.mint;}
function plot(rows){
 const vals=(rows||[]).map(r=>Number(r.price)).filter(p=>Number.isFinite(p)&&p>0);
 if(vals.length<2)return '<span class="tiny">Historique en cours</span>';
 let mn=Math.min(...vals),mx=Math.max(...vals);if(mx===mn){mx+=mn*.001;mn-=mn*.001}
 const coordinates=vals.map((v,i)=>`${(i/(vals.length-1)*110).toFixed(1)},${(32-(v-mn)/(mx-mn)*27).toFixed(1)}`).join(' ');
 const stroke=vals.at(-1)>=vals[0]?'#6ee6b8':'#ff8b9c';
 return `<svg class="sparkline" viewBox="0 0 112 35" aria-label="Prix relevés lors des scans"><polyline points="${coordinates}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>`;
}
function rank(c){return ({a_etudier:3,surveillance:2,incomplet:1,risque:0}[c.status]??0)}
function setNotice(message,seconds=7){noticeText=message;noticeUntil=Date.now()+seconds*1000;updateScanStatus();}
function clock(ts){return ts?new Date(ts*1000).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';}
function updateScanStatus(){
 const st=current.status||{}, now=Date.now()/1000, demo=st.mode==='demo';
 const active=Boolean(st.running), pending=!active&&Date.now()<manualPendingUntil;
 const failed=!demo&&!active&&st.last_outcome==='error';
 const remaining=Math.max(0,Math.ceil((st.gecko_resume_at||0)-now));
 if($('geckoCompact'))$('geckoCompact').textContent=remaining?`Gecko : pause ${remaining} s (limite API), scanner actif`:'Gecko : vérification facultative';
 const panel=$('scanPanel');
 panel.classList.toggle('is-scanning',!demo&&active);
 panel.classList.toggle('is-error',!demo&&(!connectionOk||failed));
 panel.classList.toggle('is-demo',demo);
 $('scanCycle').textContent='Cycle '+(st.cycle??'—');
 let title, detail, progress=0;
 if(!connectionOk){title='Connexion au bot impossible';detail='Vérifie que MemeRadar est toujours lancé sur ton PC.';}
 else if(demo){title='Mode démo — aucune analyse réelle';detail='Les six tokens sont fictifs. Démarre START_MEMERADAR.bat pour les vrais marchés.';}
 else if(active){
   title='Analyse en cours…';
   const phase=st.phase||'Analyse des tokens';
   const done=Number(st.progress_done||0),total=Number(st.progress_total||0);
   const fraction=total>0?Math.min(1,done/total):0;
   progress=phase.includes('pools')?10:phase.includes('wallets')?23:phase.includes('prix')?39:phase.includes('cotations')?55:Math.round(62+38*fraction);
   detail=phase+(total?' · '+done+'/'+total+' tokens traités':'')+' · démarré à '+clock(st.started_at);
 }
 else if(pending){title='Actualisation manuelle demandée…';detail='Le prochain cycle va commencer dès que le scanner sera disponible.';progress=6;}
 else if(failed){title='Dernier scan interrompu';detail='Le bot réessaiera automatiquement. Consulte les diagnostics sous la liste.';}
 else if(st.last_scan){
   title='Scanner en veille active';
   detail=(st.scanned??0)+' tokens vérifiés au dernier passage'+(st.new_tokens?' · '+st.new_tokens+' nouveaux':'')+
     (st.duration_seconds!=null?' · scan de '+Number(st.duration_seconds).toFixed(1)+' s':'');
 }else{title='Initialisation du scanner…';detail='Le premier cycle de découverte va commencer.';}
 const next=Number(st.next_scan||0);
 let nextLabel='—';
 if(demo)nextLabel='Désactivé';
 else if(active)nextLabel='Après le scan';
 else if(pending)nextLabel='Imminent';
 else if(next){
   const remaining=Math.max(0,Math.ceil(next-now));
   nextLabel=remaining?`Dans ${remaining} s`:'Démarrage imminent';
   if(st.finished_at&&next>st.finished_at&&connectionOk)
     progress=Math.round(Math.max(0,Math.min(1,(now-st.finished_at)/(next-st.finished_at)))*100);
 }
 $('scanTitle').textContent=title;$('scanDetail').textContent=detail;
 $('scanLast').textContent=st.last_scan?clock(st.last_scan)+' · '+since(st.last_scan):'Jamais';
 $('scanNext').textContent=nextLabel;
 $('scanFrontend').textContent=lastDataAt?'il y a '+since(lastDataAt):'En attente';
 $('scanProgress').style.width=Math.max(0,Math.min(100,progress))+'%';
 $('scanTrack').setAttribute('aria-valuenow',String(Math.max(0,Math.min(100,progress))));
 $('lastScan').textContent=st.last_scan?'Dernier scan : il y a '+since(st.last_scan)+' · '+(st.scanned??0)+' tokens analysés':'En attente du premier scan';
 $('systemText').textContent=!connectionOk?'DÉCONNECTÉ':demo?'DÉMONSTRATION':active?'ANALYSE EN COURS':failed?'SCAN EN ERREUR':st.last_scan?'SURVEILLANCE ACTIVE':'CONNEXION EN COURS';
 $('signalDot').className='signal-dot'+(connectionOk&&!failed&&!active?' on':'');
 $('refreshButton').disabled=!connectionOk||demo||active||pending||refreshInFlight;
 $('restartButton').disabled=!connectionOk||demo||restarting;
 $('refreshButton').textContent=active?'↻  Analyse en cours…':pending?'↻  Scan demandé…':'↻  Scanner maintenant';
 $('scanNotice').textContent=noticeText;
 $('scanNotice').classList.toggle('hidden',!noticeText||Date.now()>noticeUntil);
}
function render(){
 const s=current.stats||{}, st=current.status||{};
 $('statTotal').textContent=(s.live??s.total??0)+' / '+(s.total??0);$('statInteresting').textContent=s.interesting??0;$('statIncomplete').textContent=s.incomplete??0;$('statRisky').textContent=s.risky??0;
 $('demoBanner').classList.toggle('hidden',st.mode!=='demo');updateScanStatus();
 const remaining=Math.max(0,Math.ceil((st.gecko_resume_at||0)-Date.now()/1000));
 $('geckoCompact').textContent=remaining?`Gecko : pause ${remaining} s (limite API), scanner actif`:'Gecko : disponible pour vérification';
 const warnings=(st.errors||[]).slice(0,4);
 $('warningBox').classList.toggle('hidden',warnings.length===0);
 $('warningBox').textContent=warnings.length?'Sources / diagnostics : '+warnings.join(' · '):'';
 const text=$('search').value.trim().toLowerCase(), filter=$('filter').value, sort=$('sort').value;
 let coins=(current.coins||[]).filter(c=>qualityPasses(c)&&
  (filter==='all'||(filter==='favorites'?favorites.has(coinId(c)):filter==='signals'?(c.patterns||[]).length>0:c.status===filter))&&
  ((c.symbol||'').toLowerCase().includes(text)||(c.name||'').toLowerCase().includes(text)||(c.mint||'').toLowerCase().includes(text)));
 const n=coins.length;
 const all=current.coins||[];
 const riskCount=all.filter(c=>c.status==='risque').length;
 const scoreCount=all.filter(c=>Number(c.score)<=quality.score).length;
 const safeCount=all.filter(c=>c.status!=='risque'&&c.fresh!==false).length;
 const staleCount=all.filter(c=>c.fresh===false).length;
 $('visibleCount').textContent=n+' token'+(n===1?'':'s')+' affiché'+(n===1?'':'s')+' sur '+all.length+(s.stored>all.length?' (base : '+s.stored+')':'');
 $('selectionDiagnostic').textContent=`${staleCount} archivés (données > 5 min) · ${riskCount} avec alertes de risque · ${scoreCount} sous la note minimale · ${safeCount} sans alerte de risque · ${st.new_candidates??0} nouveaux candidats proposés au dernier cycle · ${st.pairs_found??0} paires DEX trouvées sur ${st.scanned??0} tentées`;
 coins.sort((a,b)=>sort==='signals'?(b.patterns?.length||0)-(a.patterns?.length||0)||b.score-a.score:sort==='score'?b.score-a.score:sort==='recent'?b.first_seen-a.first_seen:
  sort==='age'?(a.age_min??Infinity)-(b.age_min??Infinity):rank(b)-rank(a)||(b.priority_score??b.score)-(a.priority_score??a.score)||b.score-a.score);
 $('coinList').innerHTML=coins.length?coins.map(c=>{
   const label=statuses[c.status]||['INCONNU',''];
   return `<button type="button" class="coin-row ${c.fresh===false?'coin-expired':''}" data-mint="${esc(c.mint)}">
    <div class="token-title"><div class="coin-avatar">${esc((c.symbol||'?').slice(0,2).toUpperCase())}</div><div><div class="coin-label"><span class="symbol">$${esc(c.symbol)}<small>${esc((c.name||'').slice(0,17))}</small></span></div><span class="pill ${label[1]}">${label[0]}</span>${(c.sources||[]).some(x=>x.startsWith('j7'))?'<span class="pill surveillance">J7</span>':''}${c.pre_impulse?'<span class="pill pre-impulse">PRÉ-IMPULSION · EXPÉRIMENTAL</span>':c.prewatch?'<span class="pill prewatch">PRESSION À CONFIRMER</span>':''}<div class="tiny">${c.fresh===false?'Ancienne cotation · ' : 'Vérifié il y a '}${since(c.last_seen)}</div>${(c.patterns||[]).length?`<div class="signal-mini">✦ ${esc(c.patterns.map(x=>x.label).join(" · "))}</div>`:""}</div></div>
    <div><b>${price(c.price_usd)}</b><div class="tiny">${c.fresh===false?'PRIX HISTORIQUE · ':''}${shortMint(c.mint)}</div></div>
    <div><b>${money(c.liquidity_usd)}</b><div class="tiny">1h : ${money(c.volume_h1_usd)}</div></div>
    <div><b class="${color(c.change_m5_pct)}">${pct(c.change_m5_pct)}</b><div class="tiny">Âge ${age(c.age_min)}</div></div>
    <div>${plot(c.history)}<div class="change-small ${color(c.observed_change_pct)}">Depuis 1er relevé : ${pct(c.observed_change_pct)}</div></div>
    <div><div class="score">${esc(c.score)}<small>/100</small></div><div class="tiny">${c.fresh===false?'score ancien · ':''}preuves ${esc(c.coverage)} %</div></div></button>`;
 }).join(''):`<div class="empty"><strong>${safeCount?'Aucun candidat ne dépasse les filtres actuels.':'Aucun candidat sans alerte de risque actuellement.'}</strong><p>${safeCount?'Il existe '+safeCount+' token(s) sans alerte critique parmi les résultats. Tu peux les consulter sans les présenter comme de bonnes opportunités.':'Le bot continue de chercher. Ne désactive pas les alertes de risque pour forcer un résultat.'}</p>${safeCount?'<button class="outline-button" id="safeCandidatesButton" type="button">Voir les candidats sans alerte (tous scores)</button>':''}</div>`;
 if($('safeCandidatesButton'))$('safeCandidatesButton').addEventListener('click',()=>{
   quality.score=0;quality.hideRisks=true;quality.hideStale=true;quality.signalsOnly=false;quality.coverage=0;
   $('search').value='';$('filter').value='all';saveQuality();syncQualityControls();render();
 });
 document.querySelectorAll('.coin-row').forEach(btn=>btn.addEventListener('click',()=>openCoin(btn.dataset.mint)));
}
function chips(items,kind){return (items||[]).length?items.map(x=>`<span class="chip ${kind||''}">${esc(x)}</span>`).join(''):'<span class="muted">Aucun élément enregistré</span>';}
function openCoin(mint){
 selected=mint;const c=(current.coins||[]).find(x=>x.mint===mint);if(!c)return;
 const fav=favorites.has(mint), label=statuses[c.status]?.[0]||'INCONNU',s=c.safety_summary||{};
 $('detailTitle').textContent='$'+(c.symbol||'?')+' · '+(c.name||'Coin');
 const url=current.status.mode==='demo'?'':`https://dexscreener.com/solana/${encodeURIComponent(c.pair_address||mint)}`;
 $('detailBody').innerHTML=`<div class="detail-intro"><span class="pill ${esc(c.status)}">${label}</span>${c.fresh===false?'<div class="stale-warning">⚠ Cotation historique : ce token n’a pas été revérifié depuis ' + since(c.last_seen) + '. Ne pas utiliser ce prix ni cette ancienne note pour décider d’acheter.</div>':''}<p>Mint : <code>${esc(mint)}</code></p>
 <p>Découvert il y a ${since(c.first_seen)} · dernière vérification il y a ${since(c.last_seen)}</p>
 <p>Paire analysée : <code>${esc(c.pair_address||'inconnue')}</code> · DEX : ${esc(c.pair_dex||'inconnu')} · sélection basée sur la liquidité du pool.</p></div>
 <div class="detail-metrics">
 <div class="detail-stat"><small>Score non calibré</small><strong>${esc(c.score)}/100</strong></div>
 <div class="detail-stat"><small>Preuves présentes</small><strong>${esc(c.coverage)} %</strong></div>
 <div class="detail-stat"><small>Prix indicatif</small><strong>${price(c.price_usd)}</strong></div>
 <div class="detail-stat"><small>Liquidité</small><strong>${money(c.liquidity_usd)}</strong></div>
 <div class="detail-stat"><small>Volume sur 1 h</small><strong>${money(c.volume_h1_usd)}</strong></div>
 <div class="detail-stat"><small>Variation 5 min</small><strong class="${color(c.change_m5_pct)}">${pct(c.change_m5_pct)}</strong></div>
 <div class="detail-stat"><small>Achats / Ventes 1 h</small><strong>${c.buys_h1??'—'} / ${c.sells_h1??'—'}</strong></div>
 <div class="detail-stat"><small>Achats / ventes 5 min</small><strong>${c.pressure_buys_m5??'—'} / ${c.pressure_sells_m5??'—'}</strong></div>
 <div class="detail-stat"><small>Volume 5 min</small><strong>${money(c.volume_m5_usd)}</strong></div>
 <div class="detail-stat"><small>Top 10 détenteurs</small><strong>${s.top10_pct==null?'Inconnu':pct(s.top10_pct)}</strong></div>
 <div class="detail-stat"><small>Risque RugCheck</small><strong>${s.rugcheck_score??'Inconnu'}</strong></div></div>
 <div class="details-section"><h3>Détection avant mouvement (expérimentale)</h3>
 <p>${c.pre_impulse?'Deux relevés compatibles : pression acheteuse observée alors que le prix restait relativement stable. Ce n’est pas une prédiction de hausse.':c.prewatch?'Un premier relevé correspond à une pression acheteuse sur prix relativement stable. Second contrôle en attente.':'Aucun motif de pré-impulsion confirmé.'} Les comptes distincts ne sont pas vérifiés par DexScreener ; certains échanges peuvent être artificiels.</p>
 ${c.pre_impulse_first_at?`<p class="muted">Première confirmation enregistrée : ${clock(c.pre_impulse_first_at)} · prix initial ${price(c.pre_impulse_first_price)}. Une confirmation passée ne vaut pas signal actuel.</p>`:''}</div>
 <div class="details-section"><h3>Attention sociale liée à ce coin</h3><p>Priorité expérimentale : ${esc(c.priority_score??'—')}/100. ${esc(c.social_context?.authors_5m??0)} auteurs distincts sur 5 min, dont ${esc(c.social_context?.j7_badged_authors_10m??0)} badges signalés J7 et ${esc(c.social_context?.verified_influential_authors_10m??0)} confirmés par l’API X sur 10 min, contre ${esc(c.social_context?.authors_previous_5m??0)} auparavant. Indépendance et intention non vérifiées.</p>
${(c.social_mentions||[]).map(p=>`<p>@${esc(p.author)} : ${esc(p.text)} <a href="https://x.com/${encodeURIComponent(p.author)}/status/${encodeURIComponent(p.id)}" target="_blank" rel="noopener noreferrer">Voir ↗</a></p>`).join('')}
</div><div class="details-section"><h3>Historique des prix relevés</h3><div style="margin:8px 0">${plot(c.history)}</div><span class="muted">${c.history?.length||0} relevés disponibles. La courbe n’est pas un historique complet du marché.</span></div>
 <div class="details-section"><h3>Signaux observés (méthodes combinées)</h3><div class="chips">${(c.patterns||[]).length?c.patterns.map(x=>`<div class="pattern" title="${esc(x.why)}"><strong>✦ ${esc(x.label)}</strong><small>${esc(x.why)}</small></div>`).join(""):'<span class="muted">Aucun signal spécifique enregistré pour le moment.</span>'}</div></div>
 <div class="details-section"><h3>Motifs favorables</h3><div class="chips">${chips(c.positives,'good')}</div></div>
 <div class="details-section"><h3>Décomposition du score</h3><div class="scoring-pieces">${Object.entries(c.pieces||{}).map(([k,v])=>`<div><span>${esc(k)}</span><strong>+${Number(v).toFixed(1)}</strong></div>`).join("")||'<span class="muted">Non disponible</span>'}</div><p class="muted">Score heuristique non calibré, les valeurs manquantes valent zéro, et un risque critique bloque le statut « À étudier ».</p></div>
 <div class="details-section"><h3>Risques détectés</h3><div class="chips">${chips(c.risks,'bad')}</div></div>
 <div class="details-section"><h3>Points non vérifiés</h3><div class="chips">${chips(c.unknown)}</div></div>
 <div class="details-section"><h3>Sources et wallets publics</h3><div class="chips">${chips((c.sources||[]).concat((c.wallets||[]).map(x=>'Solde augmenté : '+x.slice(0,7)+'…')))}</div>
 <p class="muted">Un solde de token qui augmente ne prouve pas un achat ; les wallets distincts peuvent appartenir à une même personne. Les boosts publicitaires ne donnent aucun point de qualité.</p></div>
 <div class="modal-note">Contrôles incomplets ≠ token sûr. Un score élevé ne signifie pas un futur pump. Vérifie la liquidité réelle, les détenteurs et la possibilité de vendre avant toute décision manuelle.</div>
 <div class="links"><button id="favoriteButton" class="outline-button">${fav?'★ Retirer des favoris':'☆ Ajouter aux favoris'}</button>${url?`<a href="${url}" target="_blank" rel="noopener noreferrer">Ouvrir DexScreener ↗</a>`:''}</div>`;
 $('favoriteButton').addEventListener('click',()=>{if(favorites.has(mint))favorites.delete(mint);else favorites.add(mint);
  localStorage.setItem('radar_favorites',JSON.stringify([...favorites]));openCoin(mint);render()});
 $('overlay').classList.remove('hidden');
}
$('closeModal').addEventListener('click',()=>$('overlay').classList.add('hidden'));
$('overlay').addEventListener('click',(e)=>{if(e.target===$('overlay'))$('overlay').classList.add('hidden')});
document.addEventListener('keydown',(e)=>{if(e.key==='Escape')$('overlay').classList.add('hidden')});
$('search').addEventListener('input',render);$('filter').addEventListener('change',()=>{if($('filter').value==='expire'){quality.hideStale=false;saveQuality();syncQualityControls();}render();});$('sort').addEventListener('change',render);
$('minimumScore').addEventListener('input',()=>{
 quality.score=Number($('minimumScore').value);syncQualityControls();saveQuality();render();
});
$('hideStale').addEventListener('change',()=>{quality.hideStale=$('hideStale').checked;saveQuality();render();});
$('hideRisks').addEventListener('change',()=>{quality.hideRisks=$('hideRisks').checked;saveQuality();render();});
$('withSignalsOnly').addEventListener('change',()=>{quality.signalsOnly=$('withSignalsOnly').checked;saveQuality();render();});
$('minimumCoverage').addEventListener('change',()=>{quality.coverage=Number($('minimumCoverage').value);saveQuality();render();});
$('showAllButton').addEventListener('click',()=>{
 quality.score=0;quality.hideRisks=false;quality.hideStale=false;quality.signalsOnly=false;quality.coverage=0;
 $('search').value='';$('filter').value='all';$('sort').value='rank';
 saveQuality();syncQualityControls();render();
});
syncQualityControls();
let restarting=false, restartBeforeId=null;
$('restartButton').addEventListener('click',async()=>{
 if(restarting||!connectionOk)return;
 if(!confirm('Redémarrer tous les services MemeRadar (scanner, J7 et vérification X) ? L’historique sera conservé.'))return;
 restarting=true;restartBeforeId=current.status?.instance_id||null;$('restartButton').disabled=true;
 setNotice('Redémarrage en cours. Le navigateur se reconnectera automatiquement.',30);
 try{
  const res=await fetch('/api/restart',{method:'POST',headers:{'X-MemeRadar-Local-Action':'restart'}});
  const data=await res.json();
  if(!res.ok)throw Error(data.error||'HTTP '+res.status);
  setNotice('Services en cours de redémarrage. Reconnexion automatique…',120);
 }catch(e){restarting=false;$('restartButton').disabled=false;setNotice('Redémarrage impossible : '+e.message,20);}
});
$('refreshButton').addEventListener('click',async()=>{
 if(refreshInFlight||current.status?.running)return;
 refreshInFlight=true;updateScanStatus();
 try{
   const response=await fetch('/api/refresh',{method:'POST',headers:{'X-MemeRadar-Local-Action':'refresh'}});
   const result=await response.json();
   if(!response.ok){setNotice(result.error||'Scan déjà en cours.');}
   else{manualPendingUntil=Date.now()+15000;setNotice('Analyse manuelle programmée. Les résultats apparaîtront automatiquement.');}
   await load();
 }catch(e){setNotice('Impossible de demander un scan : '+e.message);}
 finally{refreshInFlight=false;updateScanStatus();}
});
let loading=false;
async function load(){
 if(loading)return;
 loading=true;
 try{
   const res=await fetch('/api/data',{cache:'no-store'});
   if(!res.ok)throw Error('HTTP '+res.status);
   const previousCycle=current.status?.cycle;
   const previousRunning=Boolean(current.status?.running);
   current=await res.json();connectionOk=true;lastDataAt=Date.now()/1000;
   if(restarting&&current.status?.instance_id&&current.status.instance_id!==restartBeforeId){
     restarting=false;restartBeforeId=null;$('restartButton').disabled=false;
     setNotice('Tous les services ont redémarré. Nouveau scan en cours.',8);
   }
   if(current.status?.running||current.status?.cycle!==previousCycle)manualPendingUntil=0;
   if((previousRunning||(previousCycle!==undefined&&current.status?.cycle!==previousCycle))&&
       !current.status?.running&&current.status?.last_outcome==='ok'){
     setNotice('Scan terminé : '+(current.status.scanned??0)+' tokens vérifiés'+
       (current.status.new_tokens?' · '+current.status.new_tokens+' nouveaux':''),8);
   }
   render();
   if(selected&&!$('overlay').classList.contains('hidden')){
     const modal=document.querySelector('.modal'),scroll=modal.scrollTop;
     openCoin(selected);modal.scrollTop=scroll;
   }
 }catch(e){
   connectionOk=false;updateScanStatus();
   $('warningBox').textContent='Impossible de récupérer les données : '+e.message;
   $('warningBox').classList.remove('hidden');
 }finally{loading=false;}
}
load();setInterval(load,5000);setInterval(updateScanStatus,1000);
