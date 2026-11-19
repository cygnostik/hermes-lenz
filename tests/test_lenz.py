import importlib.util
import io
import json
import unittest
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('lenz_plugin', Path(__file__).parents[1] / '__init__.py')
assert spec and spec.loader
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)

class Context:
    def __init__(self, mode='normal'): self.mode = mode
    def get_config(self, key, default=None): return self.mode

class Response:
    status = 202
    headers = {'X-Lenz-API-Version':'2026-10-11'}
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, size): return json.dumps(self.body).encode()

class LenzPluginTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for mock in (patch.object(plugin, '_state_dir', return_value=Path(temp.name)),
                     patch.object(plugin, '_get_secret', return_value='fixture')):
            mock.start()
            self.addCleanup(mock.stop)

    def paid(self, mode, action, args, amount):
        args = dict(args)
        if 'idempotency_key' not in args:
            args['idempotency_key'] = plugin._run(Context(mode), action, args)['idempotency_key']
        args['approved_credits'] = amount
        return plugin._run(Context(mode), action, args)

    def usage(self):
        return {'data': {'credits': {'remaining': 650, 'resets_at': '2090-01-01T12:00:00Z'},
                'costs': {'extract': 0, 'assess': 1, 'verify': 10, 'citation': 1},
                'cost_options': {'verify': {'depth': {'low': 5, 'standard': 10}}}}}
    def test_policy_caps_and_costs(self):
        self.assertEqual(plugin._run(Context('normal'), 'policy', {})['policy']['max_review_credits'], 32)
        self.assertEqual(plugin._run(Context('heavy'), 'policy', {})['policy']['max_review_credits'], 74)
        self.assertEqual(plugin._run(Context('moderate'), 'policy', {})['policy']['max_review_credits'], 10)
        self.assertEqual(plugin._run(Context('light'), 'policy', {})['policy']['max_review_credits'], 2)
        self.assertEqual(plugin._run(Context('critical-only'), 'policy', {})['policy']['max_review_credits'], 13)
    def test_assessment_cap_rejected_before_network(self):
        with patch.object(plugin, '_request') as req:
            with self.assertRaises(ValueError): plugin._run(Context('light'), 'assess', {'claims':['a','b','c']})
            req.assert_not_called()
    def test_critical_only_requires_explicit_flag(self):
        with patch.object(plugin, '_request') as req:
            with self.assertRaises(ValueError): plugin._run(Context('critical-only'), 'review', {'text':'a'})
            req.assert_not_called()
    def test_review_caps_private_and_webhook_disabled(self):
        with patch.object(plugin, '_request', side_effect=[self.usage(), {'data':{'review_id':'x','status':'queued'}}]) as req:
            result=self.paid('moderate', 'review', {'text':'Test claim'}, 10)
            body=req.call_args.args[2]
            self.assertEqual(body['visibility'],'private')
            self.assertEqual(body['webhook_url'],'')
            self.assertEqual(body['escalate']['max_assessments'],5)
            self.assertEqual(body['escalate']['max_verifications'],1)
            self.assertEqual(body['escalate']['depth'],'low')
            self.assertEqual(result['maximum_credits'],10)
            self.assertEqual(result['next'], {'tool':'lenz_status','id':'x','kind':'review'})
    def test_deep_check_is_server_capped_and_explicit_about_cost(self):
        with patch.object(plugin, '_request', side_effect=[self.usage(), {'data': {'review_id':'x','status':'queued'}}]) as req:
            result=self.paid('normal', 'verify', {'claim':'Two claims could be here.'}, 11)
            self.assertEqual(req.call_args.args[1],'/review')
            policy=req.call_args.args[2]['escalate']
            self.assertEqual(policy['max_assessments'],1)
            self.assertEqual(policy['max_verifications'],1)
            self.assertEqual(policy['max_citations'],0)
            self.assertEqual(result['maximum_credits'],11)
            self.assertEqual(result['next']['tool'],'lenz_status')
    def test_light_deep_disallowed(self):
        with patch.object(plugin, '_request') as req:
            with self.assertRaises(ValueError): plugin._run(Context('light'), 'verify', {'claim':'a'})
            req.assert_not_called()
    def test_verify_submission_and_status_do_not_conflate(self):
        with patch.object(plugin, '_request', return_value={'data': {'status':'processing'}}) as req:
            response=plugin._run(Context('normal'), 'status', {'kind':'verification','id':'abc-1'})
            req.assert_called_once_with('GET','/verify/status/abc-1')
            self.assertEqual(response['data']['status'],'processing')
        with self.assertRaises(ValueError): plugin._run(Context(), 'status', {'kind':'review','id':'../anything'})
    def test_http_auth_and_version_without_disclosure(self):
        with patch.object(plugin, '_get_secret', return_value='secret-token'), patch.object(plugin, '_open_request', return_value=Response({'task_id':'abc','status':'queued'})) as call:
            result=plugin._request('POST','/verify',{'claim':'test'})
            request=call.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'),'Bearer secret-token')
            self.assertEqual(request.get_header('X-lenz-api-version'),'2026-10-11')
            self.assertNotIn('secret-token',json.dumps(result))
            self.assertEqual(result['data']['status'],'queued')
    def test_provider_error_does_not_echo_body_or_key(self):
        error=HTTPError('https://lenz.io/api/v1/assess',402,'bad',{},io.BytesIO(b'secret-token'))
        with patch.object(plugin, '_get_secret', return_value='secret-token'), patch.object(plugin, '_open_request', side_effect=error):
            result=plugin._request('POST','/assess',{})
            self.assertEqual(result['http_status'],402)
            self.assertNotIn('secret-token',json.dumps(result))
            self.assertFalse(result['verified'])
    def test_redirect_is_denied_before_forwarding_credentials(self):
        handler = plugin._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, 'redirect', {}, 'https://elsewhere.invalid'))
    def test_paid_timeout_retains_reservation_and_blocks_replay(self):
        key = plugin._run(Context(), 'review', {'text':'A checkable statement.'})['idempotency_key']
        args = {'text': 'A checkable statement.', 'idempotency_key': key}
        with patch.object(plugin, '_request', side_effect=[self.usage(), TimeoutError()]):
            first = self.paid('normal', 'review', args, 32)
            self.assertEqual(first['idempotency_key'], key)
            self.assertFalse(first['verified'])
            self.assertEqual(first['budget']['reserved'],32)
        with patch.object(plugin, '_request', return_value=self.usage()) as req:
            with self.assertRaisesRegex(ValueError,'already has a reservation'):
                self.paid('normal', 'review', args, 32)
            self.assertEqual([c.args[0] for c in req.call_args_list],['GET'])
    def test_generate_opaque_key_and_reject_invalid_key_before_network(self):
        with patch.object(plugin, '_request', return_value={'data': {'status':'queued'}}) as req:
            result = plugin._run(Context('normal'), 'review', {'text':'A statement.'})
            self.assertEqual(len(result['idempotency_key']), 36)
            self.assertNotIn('statement', result['idempotency_key'])
            req.assert_not_called()
        with patch.object(plugin, '_request') as req:
            with self.assertRaises(ValueError):
                plugin._run(Context('normal'), 'verify', {'claim':'a', 'idempotency_key':'private text'})
            req.assert_not_called()
    def test_idempotency_header_is_sent(self):
        key='0bdbb253-6a15-4b72-b5e5-b3a7346c3ea4'
        with patch.object(plugin, '_get_secret', return_value='token'), patch.object(plugin, '_open_request', return_value=Response({'status':'queued'})) as call:
            plugin._request('POST', '/review', {'text':'a'}, idempotency_key=key)
            self.assertEqual(call.call_args.args[0].get_header('Idempotency-key'), key)
    def test_invalid_mode_fails_closed(self):
        with self.assertRaises(ValueError): plugin._run(Context('unknown'),'policy',{})

if __name__ == '__main__': unittest.main()
