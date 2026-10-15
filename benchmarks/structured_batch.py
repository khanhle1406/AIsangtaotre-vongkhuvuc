"""Explicit keyed planning schema; validate keys even if a gateway ignores the schema."""

import json
import threading
from typing import Any

from src.llm_agent import Program, QueryState

from .batched import PLAN_CONTRACT, BatchedAgent
from .precision import ACCURACY_CONTRACT

RUNTIME_CONTRACT = (
    "RUNTIME: cells returns plain lists of plain scalars, not objects with named attributes. "
    "Dates tagged datetime are already datetime objects: data_rows must use kind 'datetime', not 'string'; ISO-looking string cells remain strings. "
    "String-only data_rows filters also match string headers. For record/missing-value counts use observed table data bounds, preserving rows whose measure is blank; never count the heading as a record. "
    "Only the documented standard-library modules are available; numpy, pandas and scipy are unavailable, as are hasattr/getattr. Implement calculations with lists, arithmetic and loops. "
)

BOUNDARY_CONTRACT = (
    "POSTCONDITIONS: Before returning an entity from a sequential or constrained calculation, "
    "check that the returned entity itself satisfies the question's condition. A depleted global "
    "budget does not establish an individual zero allocation; zero, partial and complete are distinct. "
    "For constrained optima compare only feasible complete candidates; absent pairs are forbidden, not zero-cost. "
)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate keys before a JSON decoder can silently overwrite them."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate structured output key")
        result[key] = value
    return result


def closed_container_json(text: str) -> tuple[Any, bool]:
    """Close only missing container delimiters at EOF; never invent keys/values/quotes."""
    try:
        return json.loads(text, object_pairs_hook=unique_object), False
    except json.JSONDecodeError as error:
        if error.pos != len(text.rstrip()):
            raise
        stack: list[str] = []
        quoted = escaped = False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "{[":
                stack.append("}" if char == "{" else "]")
            elif char in "}]" and (not stack or stack.pop() != char):
                raise
        if quoted or not stack or len(stack) > 32:
            raise
        # The strict decoder still rejects incomplete values, keys and duplicate keys.
        return json.loads(
            text.rstrip() + "".join(reversed(stack)), object_pairs_hook=unique_object
        ), True


class StructuredPlanningMixin:
    """Keep the measured executor/guards; reduce ambiguous array-index generation."""

    def __init__(
        self,
        *,
        json_schema: bool = True,
        runtime_contract: bool = True,
        compact_contract: bool = False,
        boundary_contract: bool = False,
        coherent_envelope: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.json_schema = json_schema
        self.runtime_contract = runtime_contract
        self.compact_contract = compact_contract
        self.boundary_contract = boundary_contract
        self.coherent_envelope = coherent_envelope
        if coherent_envelope and any(
            self.system_prompt.count(marker) != 1
            for marker in ("Return ONE JSON object:", "CELL TYPES s/n/d/b/e/u")
        ):
            raise ValueError(
                "Coherent planning requires the documented full system template"
            )
        self.structured_state = threading.local()

    def _before_request(self, payload: dict[str, Any], state: QueryState) -> None:
        prepared = getattr(self.structured_state, "prepared_payload", None) is payload
        if prepared:
            super()._before_request(payload, state)
            return
        self.structured_state.prepared_payload = payload
        self.structured_state.structured_expected = None
        self.structured_state.original_content = None
        self.structured_state.question_texts = {}
        self.structured_state.container_repaired = False
        self.structured_state.envelope_normalization = None
        content = payload["messages"][-1]["content"]
        if content.endswith(PLAN_CONTRACT):
            raw = content.rsplit("\nQUESTIONS:\n", 1)[1].split(
                "\n" + ACCURACY_CONTRACT, 1
            )[0]
            questions = json.loads(raw)
            keys = [f"q{i}" for i in range(len(questions))]
            self.structured_state.question_texts = {
                key: question["query"]
                for key, question in zip(keys, questions, strict=True)
            }
            program = {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "result_variable": {"type": "string"},
                    "format": {"type": "object"},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "needs_verification": {"type": "boolean"},
                },
                "required": ["code"],
                "additionalProperties": False,
            }
            schema = {
                "type": "object",
                "properties": {
                    "programs": {
                        "type": "object",
                        "properties": {key: program for key in keys},
                        "required": keys,
                        "additionalProperties": False,
                    }
                },
                "required": ["programs"],
                "additionalProperties": False,
            }
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "workbook_programs", "schema": schema},
            }
            if not self.json_schema:
                payload["response_format"] = {"type": "json_object"}
            payload["messages"] = [dict(message) for message in payload["messages"]]
            if self.coherent_envelope:
                system = payload["messages"][0]["content"]
                start = system.index("Return ONE JSON object:")
                end = system.index("CELL TYPES s/n/d/b/e/u")
                payload["messages"][0]["content"] = (
                    system[:start]
                    + 'Return ONE keyed JSON object {"programs":{"q0":{"code":"Python assigning result","result_variable":"result","format":{"kind":"auto","decimals":null,"count":null,"separator":", "},"assumptions":[],"needs_verification":false}}}. '
                    + "Include exactly the requested qN keys, each with its own independently executable program. "
                    + "The keys and questions are supplied in the user message. Do not place code, result_variable, format or selection at the root. "
                    + "Selection is optional inside each program; if supplied it must cover all cells read by that program. "
                    + "format.kind must be auto, text, integer, decimal, boolean or date. "
                    + "All calculation and formatting rules below apply independently to every program.\n"
                    + system[end:]
                )
            prefix = content[: -len(PLAN_CONTRACT)]
            repeated_contract = "\n" + ACCURACY_CONTRACT + "\n"
            if self.compact_contract and prefix.endswith(repeated_contract):
                # The full system prompt retains these same semantic rules. Remove
                # only the exact application-appended suffix, never workbook data.
                prefix = prefix[: -len(repeated_contract)]
            payload["messages"][-1]["content"] = (
                prefix
                + '\nKEYED OUTPUT CONTRACT: Return {"programs":{"q0":{"code":"Python assigning result","format":{"kind":"integer"}},...}}.\nRequired keys: '
                + json.dumps(keys)
                + ". qN answers question index N; never renumber or duplicate keys. Each program runs independently. Omit selection. cell/num/label require cell addresses; age_order/data_rows/find_rows require column letters. "
                + (RUNTIME_CONTRACT if self.runtime_contract else "")
                + (BOUNDARY_CONTRACT if self.boundary_contract else "")
                + "Every result must depend on real workbook reads, never a literal answer. Lists must be lists, and labels complete. "
                "CRITICAL UNITS: keep the displayed table scale, including thousands or millions. 'How many', 'integer', 'no units' do NOT request x1000. Convert ONLY if the question explicitly requests a different scale/actual units. Return valid JSON only."
            )
            self.structured_state.structured_expected = keys
        elif self.boundary_contract:
            payload["messages"] = [dict(message) for message in payload["messages"]]
            payload["messages"][-1]["content"] += "\n" + BOUNDARY_CONTRACT
        super()._before_request(payload, state)

    def _read_response(self, response: Any) -> dict[str, Any]:
        data = super()._read_response(response)
        expected = getattr(self.structured_state, "structured_expected", None)
        if expected is None or not isinstance(data, dict):
            return data
        choices = data.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            return data
        message = choices[0].get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            return data
        text = message["content"]
        self.structured_state.original_content = text
        stripped = text.strip()
        if stripped.startswith("```") and "\n" in stripped:
            stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            envelope, repaired = closed_container_json(stripped)
            self.structured_state.container_repaired = repaired
        except ValueError:
            # Preserve malformed text for the existing application repair path;
            # usage must still be accounted for before program validation fails.
            return data
        if (
            isinstance(envelope, dict)
            and "programs" not in envelope
            and len(expected) == 1
        ):
            try:
                single = Program.model_validate(envelope)
            except ValueError:
                return data
            envelope = {"programs": {expected[0]: single.model_dump()}}
            self.structured_state.envelope_normalization = (
                "single-program-for-one-question"
            )
        if (
            not isinstance(envelope, dict)
            or not set(envelope)
            <= {
                "programs",
                "assumptions",
                "needs_verification",
                "format",
                "result_variable",
                "selection",
            }
            or "programs" not in envelope
            or not isinstance(envelope["programs"], dict)
            or set(envelope["programs"]) != set(expected)
            or ("selection" in envelope and envelope["selection"] != [])
        ):
            return data
        try:
            shared = Program.model_validate(
                {
                    "code": "result=None",
                    **{
                        key: envelope[key]
                        for key in ("format", "result_variable")
                        if key in envelope
                    },
                }
            )
        except ValueError:
            return data
        common_format = shared.format.model_dump() if "format" in envelope else {}
        neutral_format = Program(code="result=None").format.model_dump()
        common_assumptions = envelope.get("assumptions", [])
        common_review = envelope.get("needs_verification", False)
        keyed_assumptions: dict[str, list[str]] = {}
        if isinstance(common_assumptions, list) and any(
            not isinstance(value, str) for value in common_assumptions
        ):
            # Accept only an explicit bijection to the already requested keys.
            # Never infer an association from ordering or discard unknown metadata.
            for pair in common_assumptions:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or pair[0] not in expected
                    or pair[0] in keyed_assumptions
                    or not isinstance(pair[1], str)
                ):
                    return data
                keyed_assumptions[pair[0]] = [pair[1]]
            if set(keyed_assumptions) != set(expected):
                return data
            common_assumptions = []
            self.structured_state.envelope_normalization = "validated-keyed-assumptions"
        if (
            not isinstance(common_assumptions, list)
            or len(common_assumptions) > 20
            or any(not isinstance(value, str) for value in common_assumptions)
            or type(common_review) is not bool
        ):
            return data
        programs = []
        for index, key in enumerate(expected):
            try:
                raw_item = envelope["programs"][key]
                if not isinstance(raw_item, dict):
                    return data
                raw_item = dict(raw_item)
                if "result_variable" in envelope:
                    if (
                        raw_item.get("result_variable", shared.result_variable)
                        != shared.result_variable
                    ):
                        return data
                    raw_item.setdefault("result_variable", shared.result_variable)
                if common_format:
                    item_format = raw_item.get("format", {})
                    if not isinstance(item_format, dict) or any(
                        value != neutral_format[field]
                        and field in item_format
                        and item_format[field] != value
                        for field, value in common_format.items()
                    ):
                        return data
                    raw_item["format"] = {**common_format, **item_format}
                    self.structured_state.envelope_normalization = (
                        "validated-shared-format-defaults"
                    )
                if "index" in raw_item:
                    echoed_index = raw_item.pop("index")
                    if type(echoed_index) is not int or echoed_index != index:
                        return data
                if "query" in raw_item:
                    known = getattr(self.structured_state, "question_texts", {})
                    if key not in known or raw_item.pop("query") != known[key]:
                        return data
                validated = Program.model_validate(raw_item)
                item = validated.model_dump()
                item["assumptions"] = list(
                    dict.fromkeys(
                        [
                            *item.get("assumptions", []),
                            *common_assumptions,
                            *keyed_assumptions.get(key, []),
                        ]
                    )
                )
                item["needs_verification"] = common_review or item.get(
                    "needs_verification", False
                )
                program = Program.model_validate(item)
            except ValueError:
                return data
            programs.append({"index": index, **program.model_dump()})
        message["content"] = json.dumps({"programs": programs})
        if "selection" in envelope:
            # Only an empty shared declaration is neutral. Nonempty source
            # metadata must be attached to its own program; never guess ownership.
            previous = getattr(self.structured_state, "envelope_normalization", None)
            self.structured_state.envelope_normalization = "+".join(
                item for item in (previous, "validated-empty-shared-selection") if item
            )
        return data

    def _response_received(self, data: dict[str, Any], record: dict[str, Any]) -> None:
        super()._response_received(data, record)
        if getattr(self.structured_state, "structured_expected", None) is not None:
            record["requested_wire_format"] = (
                "keyed-json-schema" if self.json_schema else "keyed-json-object"
            )
            record["raw_model_content"] = self.structured_state.original_content
            if self.structured_state.container_repaired:
                record["wire_repair"] = "closed-container-tail; no keys/values changed"
            normalized = getattr(self.structured_state, "envelope_normalization", None)
            if normalized:
                record["envelope_normalization"] = normalized


class StructuredBatchedAgent(StructuredPlanningMixin, BatchedAgent):
    """Gemini gateway using the shared keyed planning and validation pipeline."""


class CoherentPlanningAgent(StructuredBatchedAgent):
    """Use matching system/user envelopes for shared planning; retain single-query repair."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(coherent_envelope=True, **kwargs)
