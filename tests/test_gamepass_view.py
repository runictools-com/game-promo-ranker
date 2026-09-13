from datetime import datetime, timezone
import unittest
from gamepass_view import enrich_gamepass


class GamePassViewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,9,13,3,tzinfo=timezone.utc)
        self.payload = {'generated_at': self.now.isoformat(), 'catalog':[{'id':'a'}, {'id':'b'}, {'id':'c'}],
                        'removed':[{'id':'a'}], 'added':[]}
        self.comparison = {'membership_checked_at': self.now.isoformat(), 'active_ids':['a','b','c'],
            'subscription':{'monthly_cents':5999,'currency':'BRL','checked_at':self.now.isoformat()},
            'prices':{key:dict(appid=str(i+1),price_cents=price,currency='BRL',checked_at=self.now.isoformat())
                      for i,(key,price) in enumerate([('a',6000),('b',5999),('c',0)])}}

    def test_strictly_above_and_never_removed(self):
        result = enrich_gamepass(self.payload,self.comparison,self.now)
        self.assertEqual([g['above_subscription'] for g in result['catalog']], [True,False,False])
        self.assertEqual(result['catalog'][0]['difference_cents'],1)
        self.assertFalse(result['removed'][0]['above_subscription'])
        self.assertEqual(result['catalog'][2]['steam']['price_cents'],0)
        self.assertNotIn('steam',self.payload['catalog'][0])

    def test_stale_prices_are_not_compared(self):
        self.comparison['prices']['a']['checked_at']='2026-09-01T00:00:00Z'
        result=enrich_gamepass(self.payload,self.comparison,self.now)
        self.assertIsNone(result['catalog'][0]['steam'])
        self.assertEqual(result['highlighted_count'],0)

    def test_stale_membership_or_subscription_cannot_highlight(self):
        for key in ('membership','subscription'):
            with self.subTest(key=key):
                if key=='membership':
                    self.comparison['membership_checked_at']='2026-09-01T00:00:00Z'
                else:
                    self.comparison['membership_checked_at']=self.now.isoformat()
                    self.comparison['subscription']['checked_at']='2026-01-01T00:00:00Z'
                self.assertEqual(enrich_gamepass(self.payload,self.comparison,self.now)['highlighted_count'],0)

    def test_wrong_currency_and_missing_membership(self):
        self.comparison['prices']['a']['currency']='USD'
        self.comparison['active_ids']=['a','b']
        result=enrich_gamepass(self.payload,self.comparison,self.now)
        self.assertEqual(result['total'],2)
        self.assertIsNone(result['catalog'][0]['steam'])
        self.assertEqual(result['highlighted_count'],0)
