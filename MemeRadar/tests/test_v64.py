"""Optional X verification is a real gate, not a large follower count or a badge spoof."""
import tempfile, time, threading, unittest
from pathlib import Path
from radar.x_verification import XVerifier, assess_profile
from radar.social import J7Feed
from radar.store import Store
from test_social import MINT,event

class XOfficialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(str(Path(self.tmp.name)/'r.db'))
    def make(self, author, user_id, followers=110000, idx='0'):
        p=event(follower=followers)
        p['id']='1990123412341234'+idx.zfill(3)
        p['author']={'handle':author,'id':str(user_id),'followersCount':followers}
        return p
    def x_data(self,author,user_id,verified=True,followers=110000):
        return {'data':{'id':str(user_id),'username':author,'verified':verified,
                'public_metrics':{'followers_count':followers,'following_count':2000,'tweet_count':5200},
                'created_at':'2018-01-01T00:00:00.000Z'}}
    def test_unverified_j7_100k_follower_does_not_boost(self):
        feed=J7Feed(self.store,token='fake-j7')
        feed.ingest(self.make('traderone','11000001'))
        ctx=self.store.social_context(MINT)
        self.assertEqual(ctx['influential_authors_10m'],1)
        self.assertEqual(ctx['verified_influential_authors_10m'],0)
    def test_verified_x_cache_and_account_link(self):
        mentions=[];calls=[]
        def fake_lookup(uid,handle,token):
            calls.append(uid)
            return assess_profile(self.x_data(handle,uid),uid,handle)
        verifier=XVerifier(self.store,on_verified=mentions.append,token='not-a-real-token',lookup=fake_lookup)
        feed=J7Feed(self.store,token='fake-j7',verifier=verifier)
        a=self.make('traderone','11000001',idx='1'); a['author']['verified']=True
        b=self.make('traderone','11000001',idx='2'); b['author']['verified']=True
        feed.ingest(a)
        feed.ingest(b)
        worker=threading.Thread(target=verifier.run,daemon=True);worker.start()
        verifier.jobs.join();verifier.stop();worker.join(timeout=2)
        ctx=self.store.social_context(MINT)
        self.assertEqual(ctx['verified_influential_authors_10m'],1) # same author, 2 posts
        self.assertEqual(len(calls),1) # X API profile cache used
        self.assertGreaterEqual(len(mentions),1)
        self.assertTrue(self.store.get_social_post('1990123412341234001')['x_verified'])
    def test_official_unverified_excluded_and_heuristic_audience_warning(self):
        p=self.make('noBadge','11000002',idx='3')
        feed=J7Feed(self.store,token='fake-j7');feed.ingest(p)
        profile=assess_profile(self.x_data('noBadge','11000002',False),'11000002','noBadge')
        self.assertTrue(self.store.attach_x_profile(p['id'],profile))
        self.assertEqual(self.store.social_context(MINT)['verified_influential_authors_10m'],0)
        new={'data':{**self.x_data('newAccount','11000002')['data'],'created_at':'2026-10-25T00:00:00Z'}}
        risky=assess_profile(new,'11000002','newAccount',now=time.mktime(time.strptime('2026-10-28','%Y-%m-%d')))
        self.assertTrue(risky['warnings'])
    def test_spoofed_x_lookup_rejected(self):
        with self.assertRaises(ValueError):
            assess_profile(self.x_data('someoneElse','11000002'),'11000002','realHandle')
    def test_j7_fields_never_make_official_badge(self):
        p=self.make('traderone','11000001')
        p['author']['isVerified']=True
        feed=J7Feed(self.store,token='fake-j7');feed.ingest(p)
        self.assertIsNone(self.store.get_social_post(p['id']).get('x_verified'))
    def test_verifier_disabled_without_token(self):
        verifier=XVerifier(self.store,token='')
        post={'id':'1990123412341234567','author':'anyTrader','author_id':'11000001','followers':50000,
              'mints':[MINT],'created_at':time.time()}
        self.assertFalse(verifier.submit(post))
        self.assertFalse(verifier.status['enabled'])

if __name__=='__main__':unittest.main()
