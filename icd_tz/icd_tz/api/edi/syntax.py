"""UN/EDIFACT syntax helpers: level A character handling and segment assembly."""

from datetime import datetime

from frappe.utils import get_datetime

# UN/EDIFACT level A repertoire. Lowercase and anything outside this set is not transmittable.
UNOA_CHARACTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,-()/'+:=?!\"%&*;<>")

# Segment terminator, element separator, component separator and the release character itself.
SERVICE_CHARACTERS = frozenset("+:'?")

RELEASE_CHARACTER = "?"
ELEMENT_SEPARATOR = "+"
COMPONENT_SEPARATOR = ":"
SEGMENT_TERMINATOR = "'"

DATE_FORMATS = {
	"102": "%Y%m%d",
	"203": "%Y%m%d%H%M",
	"204": "%Y%m%d%H%M%S",
}


def text(value, limit: int | None = None) -> str:
	"""A data value made safe to place inside a segment.

	Uppercased, stripped of characters outside level A, then the service
	characters are released so they cannot be read as structure.
	"""

	if value is None:
		return ""

	cleaned = "".join(character for character in str(value).strip().upper() if character in UNOA_CHARACTERS)
	if limit:
		cleaned = cleaned[:limit]

	return "".join(
		RELEASE_CHARACTER + character if character in SERVICE_CHARACTERS else character
		for character in cleaned
	)


def segment(tag: str, *elements) -> str:
	"""One segment, with its empty trailing elements dropped.

	An element is a string, or a list whose parts become components.
	"""

	values = [compose(element) for element in elements]

	return ELEMENT_SEPARATOR.join([tag, *trim(values)]) + SEGMENT_TERMINATOR


def compose(element) -> str:
	if isinstance(element, list | tuple):
		return COMPONENT_SEPARATOR.join(trim([str(part) if part is not None else "" for part in element]))

	return str(element) if element is not None else ""


def trim(values: list[str]) -> list[str]:
	"""Drop the empty values at the tail, the ones in the middle are positional"""

	trimmed = list(values)
	while trimmed and not trimmed[-1]:
		trimmed.pop()

	return trimmed


def edifact_datetime(value, format_code: str = "203") -> str:
	"""A date or datetime in the requested EDIFACT format, empty when there is no value"""

	if not value:
		return ""

	moment = value if isinstance(value, datetime) else get_datetime(value)

	return moment.strftime(DATE_FORMATS[format_code])


def whole_number(value) -> str:
	"""A measurement without a decimal part, which is what the carriers ask for"""

	if value in (None, ""):
		return ""

	return str(round(float(value)))


def split_segments(rendered: str) -> list[str]:
	"""The segments of a rendered message, each normalised and terminated.

	A template is free to lay its segments out over as many lines as it likes,
	and to leave elements empty where it has no value. What comes back is one
	segment per entry, which is what the interchange has to carry.
	"""

	candidates = (join_lines(part) for part in split_on(rendered, SEGMENT_TERMINATOR))

	return [normalise_segment(candidate) for candidate in candidates if candidate]


def join_lines(candidate: str) -> str:
	"""One segment on one line, however many lines the template spread it over.

	A line break is not transmittable, and the indentation that follows it is
	not data, so both are taken out rather than carried into the interchange.
	"""

	return "".join(line.strip() for line in candidate.splitlines())


def normalise_segment(segment_text: str) -> str:
	"""One segment with its empty trailing components and elements dropped.

	EDIFACT omits what it has nothing to say about, so a template can spell a
	segment out in full and let the empty tail fall away.
	"""

	tag, *elements = split_on(segment_text, ELEMENT_SEPARATOR)

	return segment(tag, *(split_on(element, COMPONENT_SEPARATOR) for element in elements))


def split_on(value: str, separator: str) -> list[str]:
	"""Split on a separator, ignoring the ones a release character protects"""

	parts = [""]
	released = False

	for character in value:
		if released:
			parts[-1] += character
			released = False
		elif character == RELEASE_CHARACTER:
			parts[-1] += character
			released = True
		elif character == separator:
			parts.append("")
		else:
			parts[-1] += character

	return parts
