"""Offline acceptance: actual admission transactions, only the HTTPS peer is a fixture."""
import concurrent.futures
import copy
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from test_lenz import Context, plugin


class Monthly(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.usage = {'credits': {'remaining': 600, 'resets_at': '2090-02-09T17:00:00Z'},
                      'costs': {'assess': 1, 'extract': 0, 'verify': 10, 'citation': 1},
                      'cost_options': {'verify': {'depth': {'low': 5, 'standard': 10}}}}
        self.posts = []
        for cm in (patch.object(plugin, '_state_dir', return_value=self.directory),
                   patch.object(plugin, '_get_secret', return_value='fixture'),
                   patch.object(plugin, '_request', side_effect=self.peer)):
            cm.start()
            self.addCleanup(cm.stop)

    def peer(self, method, path, *args, **kwargs):
        if method == 'GET':
            self.assertEqual(path, '/me/usage')
            return {'data': self.usage}
        self.posts.append(path)
        return {'data': {'status': 'queued', 'review_id': 'test-review'}}

    def quote(self, op='assess', args=None, mode='normal'):
        args = args or {'claims': ['Earth has one natural moon.']}
        result = plugin._run(Context(mode), op, args)
        self.assertFalse(result['sent'])
        return dict(args, approved_credits=result['maximum_credits'], idempotency_key=result['idempotency_key'])

    def submit(self, op='assess', args=None, mode='normal'):
        return plugin._run(Context(mode), op, self.quote(op, args, mode))

    def test_fast_defaults_to_local_preview(self):
        self.assertEqual(self.quote()['approved_credits'], 1)
        plugin._request.assert_not_called()

    def test_quote_bound_to_content_mode_and_amount(self):
        args = self.quote()
        for change,mode,reason in [({'claims':['Changed']},'normal','Preview changed'), ({},'heavy','Preview changed'),
                                  ({'approved_credits':True},'normal','Approval must match')]:
            with self.assertRaisesRegex(ValueError, reason):
                plugin._run(Context(mode),'assess',dict(args,**change))
        self.assertFalse(self.posts)
        self.assertEqual(plugin._run(Context(),'assess',args)['budget']['reserved'],1)
        self.assertNotIn(b'Earth has one', (self.directory/'monthly.sqlite3').read_bytes())

    def test_expired_preview(self):
        args = self.quote()
        import time
        with patch('time.time',return_value=time.time()+901), self.assertRaisesRegex(ValueError,'expired'):
            plugin._run(Context(),'assess',args)
        self.assertFalse(self.posts)

    def test_parallel_last_credit_and_smaller_balance(self):
        self.submit()
        self.usage['credits']['remaining'] = 1
        def attempt(i):
            try:
                self.submit(args={'claims':[f'Claim {i}']})
                return True
            except ValueError as exc:
                self.assertIn('Budget too small',str(exc))
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt,range(8))),1)
        self.assertEqual(len(self.posts),2)

    def test_exactly_500_then_provider_rollover_and_old_id_refusal(self):
        claims = {'claims': [f'Claim {i}' for i in range(20)]}
        old = self.quote('assess',claims,'heavy')
        result = plugin._run(Context('heavy'),'assess',old)
        for _ in range(24):
            result = self.submit('assess',claims,'heavy')
        self.assertEqual(result['budget']['reserved'],500)
        with self.assertRaisesRegex(ValueError,'0 available'):
            self.submit()
        self.usage['credits']['resets_at'] = '2090-03-09T17:00:00Z'
        with self.assertRaisesRegex(ValueError,'changed before'):
            self.submit()
        from datetime import datetime, timezone
        with patch('time.time',return_value=datetime(2090,2,10,tzinfo=timezone.utc).timestamp()):
            self.assertEqual(self.submit()['budget']['reserved'],1)
            with self.assertRaisesRegex(ValueError,'already has a reservation'):
                plugin._run(Context('heavy'),'assess',old)
        self.assertEqual(len(self.posts),26)

    def test_unknown_and_stale_usage_do_not_submit(self):
        orig = copy.deepcopy(self.usage)
        for value in [None, True, -1, '90']:
            self.usage['credits']['remaining'] = value
            with self.assertRaisesRegex(ValueError,'balance is unknown'):
                self.submit()
        self.usage = orig
        for value in [None,'no date','2090-02-01','2020-01-01T00:00:00Z']:
            self.usage['credits']['resets_at'] = value
            with self.assertRaisesRegex(ValueError,'reset'):
                self.submit()
        self.assertFalse(self.posts)

    def test_quote_drift_fails_closed_for_each_billing_component(self):
        orig = copy.deepcopy(self.usage)
        for section, field, value in [('costs','assess',True),('costs','citation',None),('costs','extract',False),
                                     ('costs','review',1),('cost_options','verify',{'depth':{'low':5}}),
                                     ('costs','verify',11)]:
            self.usage = copy.deepcopy(orig)
            self.usage[section][field] = value
            with self.assertRaisesRegex(ValueError,'pricing|price'):
                self.submit('review',{'text':'Draft'})
        self.assertFalse(self.posts)

    def test_zero_credit_extract_after_exhaustion_requires_explicit_quote(self):
        self.usage['credits']['remaining'] = 0
        with self.assertRaisesRegex(ValueError,'0 available'):
            self.submit()
        self.assertEqual(self.submit('extract',{'text':'Neutral.'})['budget']['reserved'],0)
        self.assertEqual(self.posts,['/extract'])

    def test_corrupt_ledger_fails_closed(self):
        (self.directory/'monthly.sqlite3').write_bytes(b'not a database')
        with self.assertRaisesRegex(ValueError,'Cannot save a local preview'):
            self.submit()
        self.assertFalse(self.posts)
