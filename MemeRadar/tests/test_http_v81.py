import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from main import make_handler
from radar.engine import Radar

class HttpAudit(unittest.TestCase):
 def test_live_readonly_routes_and_horizons(self):
  with tempfile.TemporaryDirectory() as tmp:
   radar=Radar(Path(tmp)/'radar.db',Path(tmp)/'wallets.txt')
   server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(radar))
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    url='http://127.0.0.1:'+str(server.server_port)
    for route in ('/api/data','/api/intelligence','/api/evaluation?horizon=21600'):
     with urlopen(url+route) as r:
      self.assertEqual(r.status,200);json.loads(r.read())
    with self.assertRaises(HTTPError) as err:urlopen(url+'/api/evaluation?horizon=999')
    self.assertEqual(err.exception.code,400)
    with urlopen(url+'/') as r:
     text=r.read().decode();self.assertIn('id="restart"',text);self.assertIn('id="minScore"',text)
    with urlopen(url+'/v8.js') as r:self.assertIn('async function poll',r.read().decode())
   finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
