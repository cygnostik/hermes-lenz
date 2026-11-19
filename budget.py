"""Monthly admission ledger. Only opaque request IDs, reset times and amounts persist."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import sqlite3
import time

LIMIT = 500


def quote_tag(request_id, path, body, amount, mode):
    # A preview is a bearer capability, not proof of human identity. Persist
    # neither the unspent capability nor a guessable digest of the claim.
    payload = json.dumps([path, body, amount, mode], sort_keys=True).encode()
    return hmac.new(request_id.encode(), payload, hashlib.sha256).digest()


def save_preview(directory, tag):
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(sqlite3.connect(directory / 'monthly.sqlite3')) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS previews (tag BLOB PRIMARY KEY, expires REAL NOT NULL)')
            now = time.time()
            db.execute('DELETE FROM previews WHERE expires<=?', (now,))
            db.execute('INSERT OR REPLACE INTO previews VALUES (?,?)', (tag, now+900))
    except (sqlite3.Error, OSError):
        raise ValueError('Cannot save a local preview. Check this profile’s budget directory; nothing sent.') from None


def reset_epoch(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.utcoffset() is None:
            raise ValueError
        return dt.astimezone(timezone.utc).timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValueError('Lenz did not report a timezone-qualified reset. No content sent.') from None


def admit(directory, credits, amount=0, request_id=None, tag=None):
    """Serialize period selection, duplicate check and reservation before any POST.

    Use the opening balance as an additional conservative ceiling: concurrent
    submissions may have seen the same provider snapshot before either charged.
    Never return credit on failure, timeout, refund or a smaller final bill.
    """
    remaining = credits.get('remaining') if isinstance(credits, dict) else None
    if type(remaining) is not int or remaining < 0:
        raise ValueError('Lenz balance is unknown. No content sent.')
    end = reset_epoch(credits.get('resets_at'))
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(sqlite3.connect(directory / 'monthly.sqlite3', timeout=5)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS periods (ends REAL PRIMARY KEY, opening INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, ends REAL NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0))')
            db.execute('CREATE TABLE IF NOT EXISTS previews (tag BLOB PRIMARY KEY, expires REAL NOT NULL)')
            prior = db.execute('SELECT ends, opening FROM periods ORDER BY ends DESC LIMIT 1').fetchone()
            now = time.time()
            if end <= now or (prior and end != prior[0] and (now < prior[0] or end < prior[0])):
                raise ValueError('Lenz reset is stale or changed before the previous period ended. Check the connected account and try usage later; no content sent.')
            if not prior or prior[0] != end:
                opening = min(LIMIT, remaining)
                # A read-only usage check or free extraction must not fix the opening balance.
                if amount:
                    db.execute('INSERT INTO periods VALUES (?, ?)', (end, opening))
            else:
                opening = prior[1]
            used, = db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations WHERE ends=?', (end,)).fetchone()
            available = min(opening - used, remaining)
            if request_id and db.execute('SELECT 1 FROM reservations WHERE id=?', (request_id,)).fetchone():
                raise ValueError('This request ID already has a reservation. Check the existing result or Lenz activity; it will not be sent again.')
            if request_id:
                if db.execute('DELETE FROM previews WHERE tag=? AND expires>?', (tag, now)).rowcount != 1:
                    raise ValueError('Preview changed, expired or already used. Nothing sent. Preview the exact input again and ask before submitting.')
            if amount:
                if amount > available:
                    raise ValueError(f'Budget too small: this check needs room for {amount} credits; {available} available. Choose a smaller check or wait for the Lenz reset. Nothing sent.')
                # Remember a lower live balance. Two callers holding the same
                # low balance snapshot cannot both spend its last credit.
                db.execute('UPDATE periods SET opening=? WHERE ends=?', (used + available, end))
                db.execute('INSERT INTO reservations VALUES (?,?,?)', (request_id, end, amount))
            return {'monthly_cap': LIMIT, 'reserved': used + amount, 'local_remaining': LIMIT-used-amount,
                    'available_after_reservations': available-amount, 'account_remaining_at_preflight': remaining,
                    'provider_resets_at': credits['resets_at']}
    except (sqlite3.Error, OSError):
        raise ValueError('The local Lenz budget is locked or unreadable. No submission; restore access to this profile’s budget before trying again.') from None
