"use strict";
// Display is intentionally read-only. No client-side J7 JWT or X scraping.
(function(){
 const compact=document.getElementById('j7Compact');
 const state=document.getElementById('socialState');
 const stats=document.getElementById('socialStats');
 const list=document.getElementById('socialPosts');
 const help=document.getElementById('socialHelp');
 const tabs=[...document.querySelectorAll('[data-j7-filter]')];
 const noReplies=document.getElementById('socialNoReplies');
 if(!compact||!state||!stats||!list)return;
 let busy=false, filter='relevant', latest=null, lastKey='';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={inactive:'désactivé',starting:'initialisation',connecting:'connexion',connected:'connecté',disconnected:'déconnecté',error:'erreur de connexion',auth_error:'session refusée',missing_library:'dépendance manquante',demo:'démo'};
 const tokenWords=/\b(?:meme\s?coin|memecoin|pump\.fun|rugcheck|dexscreener|geckoterminal|raydium|jupiter|launchpad|token launch|contract address|solana|crypto|altcoin|web3|blockchain|bitcoin|ethereum|onchain|on-chain)\b/i;
 const memeWords=/(?:\b(?:meme\s?coin|memecoin|pump\.fun|rugcheck|dexscreener|solana|raydium|launchpad|token launch|contract address)\b)/i;
 function relevant(p){return (p.mints||[]).length>0 || tokenWords.test(p.text||'');}
 function ago(ts){if(!ts)return '—';let n=Math.max(0,Math.floor((Date.now()/1000-ts)));return n<60?'il y a '+n+' s':n<3600?'il y a '+Math.floor(n/60)+' min':'il y a '+Math.floor(n/3600)+' h';}
 function nfmt(n){return typeof n==='number'?new Intl.NumberFormat('fr-FR',{notation:'compact',maximumFractionDigits:1}).format(n):'inconnu';}
 function update(){
  if(!latest)return;
  const s=latest.status||{}, d=latest.diagnostics||{};
  const connected=s.connected && s.upstream_connected!==false;
  const label=labels[s.state]||s.state||'en attente';
  compact.textContent='J7 : '+label+(s.error?' · '+s.error:'');
  compact.title=s.last_event?'Dernier événement : '+new Date(s.last_event*1000).toLocaleTimeString('fr-FR'):'Aucun événement';
  state.innerHTML='<span class="social-dot '+(connected?'ok':'')+'"></span> '+esc(label)+(connected?' · flux actif':'');
  const posts=latest.posts||[];
  const ca=posts.filter(p=>!p.deleted&&(p.mints||[]).length).length;
  const rel=posts.filter(p=>!p.deleted&&relevant(p)).length;
  stats.innerHTML=`<span><strong>${Number(s.received||0)}</strong> tweets uniques reçus</span><span><strong>${Number(d.stored_posts||0)}</strong> conservés</span><span><strong>${Number(d.linked_posts||0)}</strong> tweets avec CA (total)</span><span><strong>${Number(d.mint_mentions||0)}</strong> liens tweet–contrat</span><span><strong>${rel}</strong> pertinents parmi les ${posts.length} récents</span>`;
  const accountBox=document.getElementById('socialAccounts');
  const coverage=s.account_coverage||{};
  if(accountBox){
   if(coverage.state==='ok'){
    const accounts=(coverage.accounts||[]).map(a=>{
     const icon=a.status==='tracked'?'●':a.status==='available_free'?'◇':'×';
     const explain=a.status==='tracked'?'dans ta liste J7':a.status==='available_free'?'disponible à ajouter dans J7':a.status==='masked'?'masqué':'non confirmé dans ton flux';
     return `<span class="account-chip">${icon} @${esc(a.handle)} <small>${esc(explain)}</small></span>`;
    }).join('');
    accountBox.innerHTML=`<strong>Couverture J7 : ${coverage.tracked}/${coverage.total} comptes prioritaires surveillés</strong><div class="account-chips">${accounts}</div><small>Audit en lecture seule de ton abonnement. Un compte absent doit être ajouté dans J7, sans achat automatique de créneaux.</small>`;
   }else{
    accountBox.textContent=coverage.state==='error'?'Liste des comptes J7 indisponible (vérifier le jeton ou les droits).':
     coverage.state==='no_token'?'Jeton J7 absent : comptes non vérifiés.':'Vérification des comptes suivis par J7 en cours…';
   }
  }
  const official=latest.x_verification||{};
  help.textContent=`${ca} tweet(s) avec contrat parmi les ${posts.length} plus récents · ${s.new_mints||0} association(s) CA détectée(s) · Badges X rapportés par J7 (non audités) · Vérification API X ${official.enabled?'activée':'facultative et désactivée'} · La part d'abonnés bots reste inconnue.`;
  const candidates=posts.filter(p=>!p.deleted && (filter==='all'||(filter==='contracts'?(p.mints||[]).length>0:relevant(p))) && (!noReplies.checked||(!p.is_reply&&!p.is_repost)));
  const key=JSON.stringify([filter,noReplies.checked,candidates.map(p=>[p.id,p.text,p.mints,p.tickers,p.followers,p.j7_verified,p.j7_parody,p.x_verified,p.x_audience_warnings,p.deleted]),s.state]);
  if(key===lastKey)return;
  lastKey=key;
  if(!candidates.length){
   let message= filter==='contracts'? 'Aucune adresse Solana détectée pour le moment. Ce n’est pas une panne du flux J7.' : filter==='relevant'?'Pas de tweet crypto correspondant aux filtres dans les 100 derniers posts. Essaie « Tout le flux ».' : 'Aucun tweet enregistré pour le moment.';
   list.innerHTML=`<div class="social-empty">${esc(message)}</div>`;return;
  }
  list.innerHTML=candidates.slice(0,35).map(p=>{
   const ca=(p.mints||[]).map(m=>`<span class="social-ca" title="Adresse Solana vérifiée">CA : <code>${esc(m.slice(0,7))}…${esc(m.slice(-6))}</code></span>`).join('');
   const ts=(p.tickers||[]).slice(0,5).map(x=>`<span class="social-ticker">$${esc(x)}</span>`).join('');
   const themes=(p.themes||[]).slice(0,5).map(x=>`<span class="social-theme" title="Expression détectée, token non confirmé">${esc(x.term)}</span>`).join('');
   const url=`https://x.com/${encodeURIComponent(p.author||'')}/status/${encodeURIComponent(p.id||'')}`;
   const explicit=(p.mints||[]).length>0;
   const text=esc((p.text||'').slice(0,460));
   const badge=p.x_verified===true?' · Badge confirmé X':p.x_verified===false?' · Badge absent selon X':p.j7_verified===true?' · Badge signalé J7':p.j7_verified===false?' · Non certifié selon J7':' · Badge inconnu';
   const signal= explicit?'Contrat Solana identifié':memeWords.test(p.text||'')?'Mention Solana / meme':tokenWords.test(p.text||'')?'Mention crypto':(p.tickers||[]).length?'Ticker non vérifié':'Publication générale';
   return `<article class="social-post ${explicit?'has-ca':''}"><div class="social-post-head"><div><strong>@${esc(p.author)}</strong><small>${nfmt(p.followers)} abonnés${esc(badge)} · ${esc(ago(p.received_at))} · ${p.is_backlog?'historique':'direct'}</small></div><span class="social-kind">${esc(signal)}</span></div><p>${text}</p><div class="social-meta">${ca}${ts}${themes}<a href="${url}" target="_blank" rel="noopener noreferrer">Voir le tweet ↗</a></div></article>`;
  }).join('');
 }
 tabs.forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.j7Filter;tabs.forEach(t=>{t.classList.toggle('selected',t===b);t.setAttribute('aria-pressed',String(t===b));});lastKey='';update();}));
 noReplies.addEventListener('change',()=>{lastKey='';update();});
 async function refresh(){
  if(busy)return;busy=true;
  try{
   const r=await fetch('/api/social',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);
   latest=await r.json();update();
  }catch(e){compact.textContent='J7 : état indisponible';state.textContent='Erreur API locale : '+e.message;}
  finally{busy=false;}
 }
 refresh();setInterval(refresh,2000);
})();
