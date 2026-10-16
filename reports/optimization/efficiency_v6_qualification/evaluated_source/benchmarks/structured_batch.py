"""Explicit keyed planning schema; validate keys even if a gateway ignores the schema."""

import json
import threading
from typing import Any

from src.llm_agent import Program, QueryState

from .batched import PLAN_CONTRACT, BatchedAgent
from .precision import ACCURACY_CONTRACT


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate keys before a JSON decoder can silently overwrite them."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate structured output key")
        result[key] = value
    return result


class StructuredPlanningMixin:
    """Keep the measured executor/guards; reduce ambiguous array-index generation."""

    def __init__(self, *, json_schema: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.json_schema = json_schema
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
            payload["messages"][-1]["content"] = (
                content[: -len(PLAN_CONTRACT)]
                + '\nKEYED OUTPUT CONTRACT: Return {"programs":{"q0":{"code":"Python assigning result","format":{"kind":"integer"}},...}}.\nRequired keys: '
                + json.dumps(keys)
                + ". qN answers question index N; never renumber or duplicate keys. Each program runs independently. Omit selection. cell/num/label require cell addresses; age_order/data_rows/find_rows require column letters. "
                "Every result must depend on real workbook reads, never a literal answer. Lists must be lists, and labels complete. "
                "CRITICAL UNITS: keep the displayed table scale, including thousands or millions. 'How many', 'integer', 'no units' do NOT request x1000. Convert ONLY if the question explicitly requests a different scale/actual units. Return valid JSON only."
            )
            self.structured_state.structured_expected = keys
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
            envelope = json.loads(stripped, object_pairs_hook=unique_object)
        except ValueError:
            # Preserve malformed text for the existing application repair path;
            # usage must still be accounted for before program validation fails.
            return data
        if (
            not isinstance(envelope, dict)
            or not set(envelope) <= {"programs", "assumptions", "needs_verification"}
            or "programs" not in envelope
            or not isinstance(envelope["programs"], dict)
            or set(envelope["programs"]) != set(expected)
        ):
            return data
        common_assumptions = envelope.get("assumptions", [])
        common_review = envelope.get("needs_verification", False)
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
                    dict.fromkeys([*item.get("assumptions", []), *common_assumptions])
                )
                item["needs_verification"] = common_review or item.get(
                    "needs_verification", False
                )
                program = Program.model_validate(item)
            except ValueError:
                return data
            programs.append({"index": index, **program.model_dump()})
        message["content"] = json.dumps({"programs": programs})
        return data

    def _response_received(self, data: dict[str, Any], record: dict[str, Any]) -> None:
        super()._response_received(data, record)
        if getattr(self.structured_state, "structured_expected", None) is not None:
            record["requested_wire_format"] = (
                "keyed-json-schema" if self.json_schema else "keyed-json-object"
            )
            record["raw_model_content"] = self.structured_state.original_content


class StructuredBatchedAgent(StructuredPlanningMixin, BatchedAgent):
    """Gemini gateway using the shared keyed planning and validation pipeline."""
