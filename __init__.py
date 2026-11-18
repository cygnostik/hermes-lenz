"""Explicit, on-demand Lenz verification for Hermes (no automatic content upload)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

_API = 'https://lenz.io/api/v1'
_VERSION = '2026-10-11'
# Caps are enforced on EACH request. They do not prevent repeated requests.
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
            'scope': 'per request only; no aggregate budget or automatic checking',
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


def _request(method, path, body=None, idempotency_key=None):
    key = _get_secret()
    if not key:
        raise ValueError('LENZ_API_KEY is not configured for Hermes.')
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
            return {'http_status': response.status, 'api_version': response.headers.get('X-Lenz-API-Version'), 'data': data}
    except urllib.error.HTTPError as exc:
        # The response body can contain sensitive input; never include it in logs or output.
        return {'error': 'Lenz API request failed', 'http_status': exc.code, 'verified': False}
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


def _post(path, body, args):
    # A new opaque UUID contains no content. The caller can reuse it for a retry.
    key = _idempotency_key(args)
    try:
        result = _request('POST', path, body, idempotency_key=key)
    except ValueError as exc:
        # Missing credentials and response-size errors do not include input or keys.
        result = {'error': str(exc), 'verified': False}
    except Exception:
        result = {'error': 'Lenz request failed; it may have completed. Reuse the same key and identical request body before retrying.', 'verified': False}
    result['idempotency_key'] = key
    result['retry_guidance'] = ('For an uncertain result, retry only with this same key and identical body '
                                '(including the same mode); Lenz retains the key for 24 hours. '
                                'A new key can cause another charge.')
    return result


def _run(ctx, action, args):
    if not isinstance(args, dict):
        raise ValueError('Tool arguments must be an object.')
    mode, p = _mode(ctx)
    policy = _policy(mode, p)
    if action == 'policy':
        return {'policy': policy}
    if action == 'usage':
        return _request('GET', '/me/usage')
    if action == 'status':
        kind = args.get('kind')
        job = _text(args.get('id'), 'id', 200)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', job):
            raise ValueError('Invalid job ID.')
        if kind == 'verification': path = '/verify/status/' + job
        elif kind == 'review': path = '/reviews/' + job
        else: raise ValueError('kind must be verification or review.')
        return _request('GET', path)
    _critical(mode, args)
    if action == 'extract':
        text = _text(args.get('text'), 'text', 50000)
        focus = args.get('focus', '')
        if not isinstance(focus, str) or len(focus) > 300:
            raise ValueError('focus must be a string of at most 300 characters.')
        result = _post('/extract', {'text': text, 'focus': focus, 'locate': True}, args)
        result['maximum_credits'] = 0
        return result
    if action == 'assess':
        claims = args.get('claims')
        if not isinstance(claims, list) or not 1 <= len(claims) <= p['assess']:
            raise ValueError(f'{mode} permits 1 to {p["assess"]} claims per assessment request; nothing was sent.')
        claims = [_text(c, 'claim', 2000) for c in claims]
        result = _post('/assess', {'claims': claims, 'suggest_rewrite': True}, args)
        result['maximum_credits'] = len(claims)
        return result
    if action == 'verify':
        if p['deep'] == 0: raise ValueError('Deep verification is disabled in light mode.')
        claim = _text(args.get('claim'), 'claim', 2000)
        # /verify may split text into several claims. Route through /review instead:
        # its server-enforced assessment and deep caps bound the paid fanout.
        body = {'text': claim, 'visibility': 'private', 'webhook_url': '', 'escalate': {
            'max_assessments': 1, 'max_verifications': 1, 'depth': p['depth'], 'max_citations': 0,
            'confidence': ['low', 'medium', 'high'], 'suggest_edits': True}}
        result = _post('/review', body, args)
        result['maximum_credits'] = 1 + (5 if p['depth'] == 'low' else 10)
        result['note'] = ('Async capped review, not a verdict; use lenz_status with kind review and '
                          'the returned review_id. A deep check depends on the assessment result.')
        return result
    if action == 'review':
        text = _text(args.get('text'), 'text', 50000)
        body = {'text': text, 'visibility': 'private', 'webhook_url': '', 'escalate': {
            'max_assessments': p['assess'], 'max_verifications': p['deep'], 'depth': p['depth'],
            'max_citations': p['citations'], 'suggest_edits': True}}
        result = _post('/review', body, args)
        result['maximum_credits'] = policy['max_review_credits']
        result['note'] = 'Async submission is not a verdict; use lenz_status with kind review and the returned review_id.'
        return result
    raise ValueError('Unknown operation.')


def register(ctx):
    ctx.register_skill('verification', Path(__file__).parent / 'skills' / 'verification' / 'SKILL.md',
                       description='Check factual claims and drafts using Lenz, with per-request credit caps.')
    critical = {'type': 'boolean', 'description': 'Set true only for an explicitly high-stakes check; required by critical-only mode.'}
    idempotency = {'type': 'string', 'description': 'Optional canonical UUIDv4 from a prior identical request; reuse it after uncertain submission. Omit to generate a new key.'}
    defs = {
        'policy': ('Show Lenz mode, per-request caps and maximum credit estimates. No API call.', {}, []),
        'extract': ('Extract checkable claims from supplied text or a public URL using Lenz. Sends this text to Lenz; costs zero credits. This is not a fact check.', {'text': {'type':'string'}, 'focus': {'type':'string'}, 'critical': critical, 'idempotency_key': idempotency}, ['text']),
        'assess': ('Quick-check an explicit list of claims with Lenz. One credit per claim; per-request mode cap applies. Results may be partial or failed.', {'claims': {'type':'array','items':{'type':'string'}}, 'critical':critical, 'idempotency_key':idempotency}, ['claims']),
        'verify': ('Submit one claim via a server-capped review (at most one assessment and one conditional deep check); poll lenz_status with kind review. Disabled in light mode.', {'claim': {'type':'string'}, 'critical':critical, 'idempotency_key':idempotency}, ['claim']),
        'review': ('Submit a draft for async Lenz review. Sends draft to Lenz; max credits and claim/citation/deep-check caps depend on mode. Poll lenz_status.', {'text': {'type':'string'}, 'critical':critical, 'idempotency_key':idempotency}, ['text']),
        'status': ('Check status/result of a previously submitted Lenz verification or review. Processing, needs_input, failed and cancelled are not verified.', {'kind': {'type':'string','enum':['verification','review']}, 'id':{'type':'string'}}, ['kind','id']),
        'usage': ('Show current Lenz account usage and credits.', {}, []),
    }
    for action, (description, properties, required) in defs.items():
        name = 'lenz_' + action
        schema = {'name': name, 'description': description, 'parameters': {'type':'object','properties':properties,'required':required}}
        def handler(params, _action=action, **kwargs):
            try:
                return json.dumps(_run(ctx, _action, params), ensure_ascii=False)
            except ValueError as exc:
                return json.dumps({'error':str(exc), 'verified':False})
            except Exception:
                # Avoid logging request bodies, API key, or provider error content.
                return json.dumps({'error':'Lenz request failed unexpectedly; no verdict was accepted.', 'verified':False})
        ctx.register_tool(name=name, toolset='lenz', schema=schema, handler=handler)
