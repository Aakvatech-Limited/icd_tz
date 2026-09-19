"""The EDIFACT message templates an EDI Partner renders, and the rules they must keep to.

A partner owns the body of its messages, from UNH to CNT. The interchange
envelope is not the partner's to write: UNB, UNT and UNZ are added around the
rendered body, so the counts and the references always agree.
"""

import frappe
from frappe import _
from jinja2 import Environment, TemplateSyntaxError, meta

from icd_tz.icd_tz.api.edi.syntax import ELEMENT_SEPARATOR, SEGMENT_TERMINATOR, split_segments

EDI_TYPES = ("CODECO", "COREOR", "COARRI", "COPARN", "COPRAR")

# The type every new partner starts with, the only one the ICD sends today.
SEEDED_EDI_TYPE = "CODECO"

TEMPLATE_DIRECTORY = ("icd_tz", "templates", "edi")

# The values a CODECO template may name. Anything else is a typo or a reach for
# something the renderer does not hand out.
CODECO_VARIABLES = (
	"reference",
	"message_code",
	"message_function",
	"sender",
	"shipping_line_code",
	"icd_un_locode",
	"container_no",
	"size",
	"equipment_status",
	"full_empty_indicator",
	"is_empty",
	"is_gate_in",
	"m_bl_no",
	"event_datetime",
	"weight",
	"seal_no",
	"transporter",
	"transporter_code",
	"truck",
	"voyage_no",
	"vessel_name",
	"call_sign",
)

# The envelope is built in code, so a template that writes it would double it.
ENVELOPE_SEGMENTS = ("UNB", "UNT", "UNZ")

# One entry per message type the ICD can actually send.
RULES = {
	"CODECO": {
		"variables": CODECO_VARIABLES,
		"mandatory_segments": ("UNH", "BGM", "NAD", "EQD", "CNT"),
		"mandatory_variables": ("reference", "container_no"),
	}
}


def get_default_template(edi_type: str) -> str:
	"""The template shipped with the app, which a partner starts from and can reset to"""

	validate_edi_type(edi_type)

	template = frappe.read_file(frappe.get_app_path(*TEMPLATE_DIRECTORY, f"{edi_type.lower()}.edi"))
	if not template:
		frappe.throw(_("No default template is shipped for {0}").format(edi_type))

	return template


@frappe.whitelist()
def get_shipped_template(edi_type: str) -> str:
	"""Read by the Reset button on the EDI Partner template row"""

	frappe.only_for("System Manager")

	return get_default_template(edi_type)


def validate_edi_type(edi_type: str):
	if edi_type not in EDI_TYPES:
		frappe.throw(_("{0} is not a known EDI type").format(edi_type))


def get_rules(edi_type: str) -> dict:
	"""What a template of this type must keep to, for a type the ICD can send"""

	validate_edi_type(edi_type)

	if edi_type not in RULES:
		frappe.throw(
			_("The ICD does not send {0} messages yet, so a template for one cannot be checked").format(
				edi_type
			)
		)

	return RULES[edi_type]


def validate_template(edi_type: str, template: str):
	"""Stop a template that cannot render, or that would render an unusable message"""

	rules = get_rules(edi_type)

	if not template:
		frappe.throw(_("The {0} template is empty").format(edi_type))

	used = get_used_variables(edi_type, template)

	# the names come first: nothing the partner wrote may run before it is known to be allowed
	check_unknown_variables(edi_type, rules, used)
	check_render(edi_type, rules, template)
	check_required_variables(edi_type, rules, used)


def get_used_variables(edi_type: str, template: str) -> set[str]:
	"""Every name the template reads, which is how a reach for `doc` is caught"""

	try:
		syntax_tree = Environment().parse(template)
	except TemplateSyntaxError as error:
		frappe.throw(
			_("The {0} template has a syntax error on line {1}: {2}").format(
				edi_type, error.lineno, error.message
			)
		)

	return meta.find_undeclared_variables(syntax_tree)


def check_unknown_variables(edi_type: str, rules: dict, used: set[str]):
	known = set(rules["variables"])

	unknown = sorted(used - known)
	if unknown:
		frappe.throw(
			_(
				"The {0} template uses values that are not available: {1}. The available values are: {2}"
			).format(edi_type, ", ".join(unknown), ", ".join(sorted(known)))
		)


def check_required_variables(edi_type: str, rules: dict, used: set[str]):
	missing = sorted(set(rules["mandatory_variables"]) - used)
	if missing:
		frappe.throw(_("The {0} template must use these values: {1}").format(edi_type, ", ".join(missing)))


def check_render(edi_type: str, rules: dict, template: str):
	"""Render the template both ways round, so a fault is found here and not at the gate.

	A template is rendered once with every value present and once with every
	value empty. A movement that carries no seal or no bill of lading is
	ordinary, and a condition that drops a mandatory segment with it would
	otherwise only show up as a message the partner rejects.
	"""

	for value, when in (("1", _("every value is present")), ("", _("a value is missing"))):
		tags = get_rendered_tags(render_sample(edi_type, rules, template, value))

		missing = [tag for tag in rules["mandatory_segments"] if tag not in tags]
		if missing:
			frappe.throw(
				_("The {0} template drops these mandatory segments when {1}: {2}").format(
					edi_type, when, ", ".join(missing)
				)
			)

		envelope = [tag for tag in ENVELOPE_SEGMENTS if tag in tags]
		if envelope:
			frappe.throw(
				_("The {0} template writes the {1} segment when {2}. The envelope is added for you.").format(
					edi_type, ", ".join(envelope), when
				)
			)


def render_sample(edi_type: str, rules: dict, template: str, value: str) -> str:
	"""The template rendered with the same stand-in for every value, to prove it runs"""

	sample = dict.fromkeys(rules["variables"], value)

	try:
		# the names were allowlisted above, and this runs against stand-ins rather than a movement
		# nosemgrep: frappe-semgrep-rules.rules.security.frappe-ssti
		return frappe.render_template(template, sample)
	except Exception as error:
		frappe.throw(_("The {0} template could not be rendered: {1}").format(edi_type, str(error)))


def get_rendered_tags(rendered: str) -> set[str]:
	"""The tag that opens each segment of a rendered message"""

	return {
		segment_text.removesuffix(SEGMENT_TERMINATOR).split(ELEMENT_SEPARATOR)[0]
		for segment_text in split_segments(rendered)
	}
