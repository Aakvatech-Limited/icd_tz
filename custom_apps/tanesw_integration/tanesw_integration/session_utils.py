"""Run code as another ERPNext user without damaging the caller's login session.

frappe.set_user(name) is meant for background jobs and scripts: it overwrites session.sid with the user NAME and
replaces session.data (which holds the CSRF token) and form_dict. "Switching back" with set_user(previous) restores
the name only, so inside a browser request the session that is saved at the end of the request is no longer the
browser's: its next call fails with "User None not found" (any request that reads TANeSW with the background watcher account).

as_user() keeps the caller's session object and puts its exact contents back afterwards, so it is safe both in web
requests and in background jobs.
"""

from contextlib import contextmanager

import frappe

_LOCALS = (
	"form_dict",
	"user_perms",
	"role_permissions",
	"cache",
	"new_doc_templates",
	"jenv_restricted",
	"jenv_unrestricted",
)


@contextmanager
def as_user(user):
	local = frappe.local
	session = local.session  # the same object the request's session handler saves at the end
	snapshot = dict(session)
	saved = {k: getattr(local, k, None) for k in _LOCALS}
	# set for this block only: the session is restored in place in the finally below
	frappe.set_user(user)  # nosemgrep: frappe-setuser
	try:
		yield
	finally:
		# set_user changed that object in place: restore it in place, so every holder of it sees the original again
		session.clear()
		session.update(snapshot)
		local.session = session
		for k, v in saved.items():
			setattr(local, k, v)
