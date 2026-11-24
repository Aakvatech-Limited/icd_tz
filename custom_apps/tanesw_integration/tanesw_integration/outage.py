"""TANeSW outage pause.

When TANeSW stops answering (a timeout or a refused connection, after the usual retry) the background jobs pause
for PAUSE_MINUTES instead of each one trying, waiting 30-60 s, failing and writing an Error Log for every vessel
(about 1,500 entries in the 18-22 Nov 2026 outage on dev).

  - The pause is one Redis key with an expiry: when it expires the next scheduled run simply tries again. If TANeSW
    is still down that run pauses again; once it answers, everything carries on. Nobody has to switch anything back.
  - Only background work is paused (no web request). A user's click always tries TANeSW, and any call that gets an
    answer lifts the pause at once.
  - Each new pause writes ONE Error Log entry; the per-vessel failures while paused write none.
"""

import sys

import frappe
from frappe.utils import add_to_date, format_datetime, get_datetime, now_datetime

PAUSE_KEY = "tanesw:outage_pause"
PAUSE_MINUTES = 10


class TANeSWUnreachable(frappe.ValidationError):
	"""TANeSW did not answer (timeout / connection refused) after the retry."""


class TANeSWPaused(frappe.ValidationError):
	"""A background call skipped because TANeSW is paused after an outage."""


def status():
	"""The current pause {until, since, reason}, or None. Expired pauses are gone by themselves."""
	# expires=True: always ask Redis, never the per-request copy, so an expired pause is seen as gone at once
	return frappe.cache.get_value(PAUSE_KEY, expires=True)


def paused():
	return bool(status())


def in_background():
	return getattr(frappe.local, "request", None) is None


def pause(reason):
	"""Start (or extend) the pause. Writes one Error Log entry per new pause, not per failed call."""
	current = status()
	until = add_to_date(now_datetime(), minutes=PAUSE_MINUTES)
	value = {
		"until": str(until),
		"since": (current or {}).get("since") or str(now_datetime()),
		"reason": reason,
	}
	frappe.cache.set_value(PAUSE_KEY, value, expires_in_sec=max(1, int(PAUSE_MINUTES * 60)))
	if not current:
		frappe.log_error(
			title=f"TANeSW not responding: background sync paused until {format_datetime(until, 'HH:mm')}",
			message=f"Reason: {reason}. Background TANeSW jobs are skipped for {PAUSE_MINUTES} minutes and then try "
			"again on their own; a user's action still tries TANeSW and lifts the pause when it gets an answer.",
		)


def resume():
	if status():
		frappe.cache.delete_value(PAUSE_KEY)


def guard():
	"""Raise TANeSWPaused for background work while paused (no network call is made)."""
	s = status()
	if s and in_background():
		raise TANeSWPaused(f"TANeSW paused after an outage until {s.get('until')}")


def log_error(title=None, message=None):
	"""frappe.log_error for the background jobs, silent for outage failures: the pause already logged them once."""
	exc = sys.exc_info()[1]
	if isinstance(exc, TANeSWPaused | TANeSWUnreachable):
		return None
	return frappe.log_error(title=title, message=message)


def until_text():
	s = status()
	return format_datetime(get_datetime(s["until"]), "HH:mm") if s else None
