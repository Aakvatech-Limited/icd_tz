"""Argument types for the whitelisted endpoints (Frappe checks them on every request).

Values from the browser arrive as text; Python callers pass numbers or parsed JSON. Scalar = one value (text or a
number): a dict or list sent there is refused. JSONish = text that is parsed as JSON, or the parsed dict / list."""

Scalar = str | int | float
JSONish = str | dict | list
