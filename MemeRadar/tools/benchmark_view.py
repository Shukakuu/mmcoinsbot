import sys,tempfile,time,json,statistics
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from radar.engine import Radar
with tempfile.TemporaryDirectory() as tmp:
 radar=Radar(Path(tmp)/'radar.db',Path(tmp)/'wallets.txt');t=time.time()
 with radar.store.db() as db:
  for i in range(300):
   m='fixture'+str(i);item={'mint':m,'name':'Test '+str(i),'symbol':'TEST','first_seen':t-60,'last_seen':t,'score':50,'status':'surveillance','price_usd':1,'first_price_usd':1}
   db.execute('INSERT INTO coins VALUES(?,?,?,?,?,?)',(m,item['symbol'],item['name'],t-60,t,json.dumps(item)))
   db.executemany('INSERT INTO prices VALUES(?,?,?,?)',[(m,t-j,1+j*.001,10000) for j in range(60)])
 elapsed=[]
 for _ in range(5):
  start=time.perf_counter();data=radar.view();elapsed.append((time.perf_counter()-start)*1000)
 print(json.dumps({'coins':300,'prices':18000,'view_median_ms':round(statistics.median(elapsed),2),'runs_ms':[round(x,2) for x in elapsed],'json_bytes':len(json.dumps(data))}))
