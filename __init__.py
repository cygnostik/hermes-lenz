"""Explicit, on-demand Lenz verification for Hermes (no automatic content upload)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .budget import LIMIT, admit, quote_tag, save_preview

_API = 'https://lenz.io/api/v1'
_VERSION = '2026-10-11'
_SETUP = 'In the target profile, open the Lenz plugin settings, save LENZ_API_KEY in the masked key field, then start a fresh session. Never paste a key in chat.'
_POLICIES = {
    'heavy':         {'assess': 20, 'deep': 5, 'depth': 'standard', 'citations': 4},
    'normal':        {'assess': 10, 'deep': 2, 'depth': 'standard', 'citations': 2},
    'moderate':      {'assess': 5,  'deep': 1, 'depth': 'low',      'citations': 0},
    'light':         {'assess': 2,  'deep': 0, 'depth': 'low',      'citations': 0},
    'critical-only': {'assess': 3,  'deep': 1, 'depth': 'standard', 'citations': 0},
}


def _mode(ctx):
    mode = str(ctx.get_config('mode', default='normal')).strip().lower().replace('_', '-')
    if mode not in _POLICIES:
        raise ValueError('Invalid Lenz mode; use heavy, normal, moderate, light, or critical-only.')
    return mode, _POLICIES[mode]


def _policy(mode, p):
    deep_cost = 5 if p['depth'] == 'low' else 10
    return {'mode': mode, 'max_assessments_per_request': p['assess'],
            'max_deep_verifications_per_review': p['deep'], 'deep_depth': p['depth'],
            'max_citations_per_review': p['citations'],
            'max_review_credits': p['assess'] + deep_cost * p['deep'] + p['citations'],
            'assess_credits_per_claim': 1, 'deep_credits_per_claim': deep_cost,
            'scope': 'Per request, within a 500-credit profile ceiling per Lenz reset period. Estimates use supported prices; live prices and balance are checked before sending.',
            'critical_only': mode == 'critical-only'}


def _critical(mode, args):
    value = args.get('critical', False)
    if not isinstance(value, bool):
        raise ValueError('critical must be a boolean.')
    if mode == 'critical-only' and not value:
        raise ValueError('Critical-only mode requires an explicitly high-stakes check and critical=true.')


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string.')
    if len(value) > maximum:
        raise ValueError(f'{name} exceeds {maximum} characters; input was not sent.')
    return value


def _get_secret():
    # Hermes profile-scoped secret route; never read credential stores directly.
    from agent.secret_scope import get_secret
    return (get_secret('LENZ_API_KEY') or '').strip()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials or user-provided content to another URL.
        return None


def _open_request(request, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _request(method, path, body=None, idempotency_key=None, *, key=None):
    key = _get_secret() if key is None else key
    if not key:
        raise ValueError('No Lenz key. ' + _SETUP)
    if not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
        raise ValueError('Malformed Lenz key. ' + _SETUP)
    payload = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(_API + path, data=payload, method=method, headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
        'Accept': 'application/json', 'X-Lenz-API-Version': _VERSION,
    })
    if idempotency_key is not None:
        req.add_header('Idempotency-Key', idempotency_key)
    try:
        with _open_request(req, timeout=90) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Lenz response exceeded 4 MiB; no verdict was accepted.')
            data = json.loads(raw)
            if not isinstance(data, dict) or response.headers.get('X-Lenz-API-Version') != _VERSION:
                raise ValueError('Unexpected Lenz response contract. No verdict accepted.')
            return {'http_status': response.status, 'api_version': response.headers.get('X-Lenz-API-Version'), 'data': data}
    except urllib.error.HTTPError as exc:
        # The response body can contain sensitive input; never include it in logs or output.
        messages = {401: 'Key rejected. ' + _SETUP, 403: 'Lenz denied access. Check this key and its permissions.',
                    402: 'Insufficient Lenz credits. Check usage or choose a smaller check.',
                    409: 'Request may already exist. Inspect Lenz activity; do not resubmit.',
                    429: 'Lenz limit reached. Check usage and any running jobs before trying later.'}
        return {'error': messages.get(exc.code, 'Lenz API request failed.'), 'http_status': exc.code, 'verified': False}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {'error': 'Lenz API unreachable or timed out; submission may have completed. Check the account before retrying a paid request.', 'verified': False}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {'error': 'Lenz returned invalid JSON; no verdict was accepted.', 'verified': False}


def _idempotency_key(args):
    value = args.get('idempotency_key')
    if value is None:
        return str(uuid.uuid4())
    if not isinstance(value, str):
        raise ValueError('idempotency_key must be a canonical UUIDv4.')
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ValueError('idempotency_key must be a canonical UUIDv4.') from None
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError('idempotency_key must be a canonical lowercase UUIDv4.')
    return value


def _state_dir():
    from hermes_constants import get_hermes_home
    return get_hermes_home() / 'lenz-budget'


def _units(path, body):
    if path == '/extract':
        return {'extract': 1}
    if path == '/assess':
        return {'assess': len(body['claims'])}
    policy = body['escalate']
    return {'extract': 1, 'assess': policy['max_assessments'], policy['depth']: policy['max_verifications'],
            'citation': policy['max_citations']}


_RATES = {'extract': 0, 'assess': 1, 'low': 5, 'standard': 10, 'citation': 1}


def _check_prices(data, units, path):
    costs, options = data.get('costs'), data.get('cost_options', {})
    if not isinstance(costs, dict) or not isinstance(options, dict):
        raise ValueError('Unknown Lenz price list. No content sent.')
    if path == '/review' and ('review' in costs or 'review' in options):
        raise ValueError('Review pricing has changed. No content sent.')
    for unit, count in units.items():
        if not count:
            continue
        price = costs.get(unit)
        if unit in ('low', 'standard'):
            verify = options.get('verify')
            depths = verify.get('depth') if isinstance(verify, dict) and set(verify) == {'depth'} else None
            price = depths.get(unit) if isinstance(depths, dict) else None
            if type(costs.get('verify')) is not int or costs['verify'] != _RATES['standard']:
                price = None
        elif unit in options:
            price = None
        if type(price) is not int or price != _RATES[unit]:
            raise ValueError(f'Unsupported or missing live price for {unit}. No content sent; check Lenz usage and plugin compatibility.')


def _post(mode, path, body, args):
    rid = _idempotency_key(args)
    units = _units(path, body)
    amount = sum(n * _RATES[k] for k, n in units.items())
    receipt = {'maximum_credits': amount, 'idempotency_key': rid}
    tag = quote_tag(rid, path, body, amount, mode)
    if 'approved_credits' not in args:
        if 'idempotency_key' in args:
            raise ValueError('Omit the request ID for a new preview. Nothing sent.')
        save_preview(_state_dir(), tag)
        return {**receipt, 'sent': False, 'units': units,
                'next': 'Preview only. Show the selected content, destination (Lenz) and maximum cost. After the user agrees, repeat with this ID, identical input and approved_credits equal to the maximum.'}
    approval = args['approved_credits']
    if type(approval) is not int or approval != amount or not args.get('idempotency_key'):
        raise ValueError('Approval must match the preview amount and include its request ID. Nothing sent.')
    key = _get_secret()
    usage = _request('GET', '/me/usage', key=key)
    if 'error' in usage:
        return {**usage, 'sent': False}
    data = usage['data']
    _check_prices(data, units, path)
    budget = admit(_state_dir(), data.get('credits') or {}, amount, rid, tag)
    try:
        result = _request('POST', path, body, idempotency_key=rid, key=key)
    except Exception:
        result = {'error': 'Lenz did not return a usable receipt.', 'verified': False}
    if path == '/review' and 'error' not in result:
        if result['data'].get('status') != 'queued' or not result['data'].get('review_id'):
            result = {'error': 'Missing review receipt.', 'verified': False}
        else:
            result['next'] = {'tool': 'lenz_status', 'kind': 'review', 'id': result['data']['review_id']}
    if 'error' in result:
        result['next'] = 'Submission may have completed. Any reserved maximum stays counted; inspect Lenz activity. Do not retry automatically.'
    return {**result, **receipt, 'budget': budget}


def _run(ctx, action, args):
    if not isinstance(args, dict):
        raise ValueError('Tool arguments must be an object.')
    mode, p = _mode(ctx)
    policy = _policy(mode, p)
    if action == 'policy':
        return {'policy': policy, 'monthly_cap': LIMIT, 'first_step': 'Ask for a local preview of a quick check, or call lenz_usage for your live balance and reset. No content sent.'}
    if action == 'usage':
        result = _request('GET', '/me/usage')
        if 'data' in result:
            result['budget'] = admit(_state_dir(), result['data'].get('credits') or {})
        return result
    if action == 'status':
        kind = args.get('kind')
        job = _text(args.get('id'), 'id', 200)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', job):
            raise ValueError('Invalid job ID.')
        if kind == 'verification': path = '/verify/status/' + job
        elif kind == 'review': path = '/reviews/' + job
        else: raise ValueError('kind must be verification or review.')
        result = _request('GET', path)
        status = result.get('data', {}).get('status')
        if status:
            result['next'] = {'completed': 'Read results, failed rows and source links; completion alone is not a verdict.',
                              'failed': 'No completed check. Inspect failure; do not resubmit.',
                              'cancelled': 'Stopped; do not present as verified.',
                              'needs_input': 'Choose a claim in Lenz. No selection or escalation is automatic.'}.get(status, 'No final result. Check this ID later; do not resubmit.')
        return result
    _critical(mode, args)
    if action == 'extract':
        text = _text(args.get('text'), 'text', 50000)
        focus = args.get('focus', '')
        if not isinstance(focus, str) or len(focus) > 300:
            raise ValueError('focus must be a string of at most 300 characters.')
        return _post(mode, '/extract', {'text': text, 'focus': focus, 'locate': True}, args)
    if action == 'assess':
        claims = args.get('claims')
        if not isinstance(claims, list) or not 1 <= len(claims) <= p['assess']:
            raise ValueError(f'{mode} permits 1 to {p["assess"]} claims per assessment request; nothing was sent.')
        claims = [_text(c, 'claim', 2000) for c in claims]
        result = _post(mode, '/assess', {'claims': claims, 'suggest_rewrite': True}, args)
        if 'data' in result:
            rows = result['data'].get('claims', [])
            checked = sum(isinstance(row, dict) and row.get('status') == 'completed' and bool(row.get('verdict')) for row in rows)
            result['summary'] = f'{checked} of {len(claims)} claims returned a quick verdict. Searched pages are not verified citations.'
        return result
    if action == 'verify':
        if p['deep'] == 0: raise ValueError('Deep verification is disabled in light mode.')
        claim = _text(args.get('claim'), 'claim', 2000)
        # /verify may split text into several claims. Route through /review instead:
        # its server-enforced assessment and deep caps bound the paid fanout.
        body = {'text': claim, 'visibility': 'private', 'webhook_url': '', 'escalate': {
            'max_assessments': 1, 'max_verifications': 1, 'depth': p['depth'], 'max_citations': 0,
            'confidence': ['low', 'medium', 'high'], 'suggest_edits': True}}
        return _post(mode, '/review', body, args)
    if action == 'review':
        text = _text(args.get('text'), 'text', 50000)
        body = {'text': text, 'visibility': 'private', 'webhook_url': '', 'escalate': {
            'max_assessments': p['assess'], 'max_verifications': p['deep'], 'depth': p['depth'],
            'max_citations': p['citations'], 'suggest_edits': True}}
        return _post(mode, '/review', body, args)
    raise ValueError('Unknown operation.')


def register(ctx):
    ctx.register_skill('verification', Path(__file__).parent / 'skills' / 'verification' / 'SKILL.md',
                       description='Preview, then check selected claims or a draft within a 500-credit monthly budget.')
    critical = {'type': 'boolean', 'description': 'Set true only for an explicitly high-stakes check; required by critical-only mode.'}
    idempotency = {'type': 'string', 'description': 'Request ID from the local preview. A reserved paid ID cannot be submitted twice.'}
    defs = {
        'policy': ('Show Lenz mode, per-request caps and maximum credit estimates. No API call.', {}, []),
        'extract': ('Extract checkable claims from supplied text or a public URL using Lenz. Sends this text to Lenz; costs zero credits. This is not a fact check.', {'text': {'type':'string'}, 'focus': {'type':'string'}, 'critical': critical, 'idempotency_key': idempotency}, ['text']),
        'assess': ('Quick-check an explicit list of claims with Lenz. One credit per claim; per-request mode cap applies. Results may be partial or failed.', {'claims': {'type':'array','items':{'type':'string'}}, 'critical':critical, 'idempotency_key':idempotency}, ['claims']),
        'verify': ('Submit one claim via a server-capped review (at most one assessment and one conditional deep check); poll lenz_status with kind review. Disabled in light mode.', {'claim': {'type':'string'}, 'critical':critical, 'idempotency_key':idempotency}, ['claim']),
        'review': ('Submit a draft for async Lenz review. Sends draft to Lenz; max credits and claim/citation/deep-check caps depend on mode. Poll lenz_status.', {'text': {'type':'string'}, 'critical':critical, 'idempotency_key':idempotency}, ['text']),
        'status': ('Check status/result of a previously submitted Lenz verification or review. Processing, needs_input, failed and cancelled are not verified.', {'kind': {'type':'string','enum':['verification','review']}, 'id':{'type':'string'}}, ['kind','id']),
        'usage': ('Read the shared Lenz balance, provider reset and local monthly room. No claim content or credit charge.', {}, []),
    }
    for action, (description, properties, required) in defs.items():
        name = 'lenz_' + action
        if 'idempotency_key' in properties:
            description = 'Preview first (local). ' + description
            properties['approved_credits'] = {'type': 'integer', 'minimum': 0, 'description': 'Omit for preview. Only after the user agrees to send this content to Lenz at the displayed maximum, pass that exact integer and the preview ID. Zero also requires consent.'}
        schema = {'name': name, 'description': description, 'parameters': {'type':'object','properties':properties,'required':required,'additionalProperties':False}}
        def handler(params, _action=action, **kwargs):
            try:
                return json.dumps(_run(ctx, _action, params), ensure_ascii=False)
            except ValueError as exc:
                return json.dumps({'error':str(exc), 'verified':False})
            except Exception:
                # Avoid logging request bodies, API key, or provider error content.
                return json.dumps({'error':'Lenz request failed unexpectedly; no verdict was accepted.', 'verified':False})
        ctx.register_tool(name=name, toolset='lenz', schema=schema, handler=handler)
