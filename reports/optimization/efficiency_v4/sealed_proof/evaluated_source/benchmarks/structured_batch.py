"""Explicit keyed planning schema; validate keys even if a gateway ignores the schema."""

import json
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


class StructuredBatchedAgent(BatchedAgent):
    """Keep the measured executor/guards; reduce ambiguous array-index generation."""

    def _before_request(self, payload: dict[str, Any], state: QueryState) -> None:
        self.request_local.structured_expected = None
        self.request_local.original_content = None
        content = payload["messages"][-1]["content"]
        if content.endswith(PLAN_CONTRACT):
            raw = content.rsplit("\nQUESTIONS:\n", 1)[1].split(
                "\n" + ACCURACY_CONTRACT, 1
            )[0]
            questions = json.loads(raw)
            keys = [f"q{i}" for i in range(len(questions))]
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
            payload["messages"] = [dict(message) for message in payload["messages"]]
            payload["messages"][-1]["content"] = (
                content[: -len(PLAN_CONTRACT)]
                + '\nKEYED OUTPUT CONTRACT: Return {"programs":{"q0":{"code":"Python assigning result","format":{"kind":"integer"}},...}}.\nRequired keys: '
                + json.dumps(keys)
                + ". qN answers question index N; never renumber or duplicate keys. Each program runs independently. Omit selection. cell/num/label require cell addresses; age_order/data_rows/find_rows require column letters. "
                "Every result must depend on real workbook reads, never a literal answer. Lists must be lists, and labels complete. "
                "CRITICAL UNITS: keep the displayed table scale, including thousands or millions. 'How many', 'integer', 'no units' do NOT request x1000. Convert ONLY if the question explicitly requests a different scale/actual units. Return valid JSON only."
            )
            self.request_local.structured_expected = keys
        super()._before_request(payload, state)

    def _read_response(self, response: Any) -> dict[str, Any]:
        data = super()._read_response(response)
        expected = getattr(self.request_local, "structured_expected", None)
        if expected is None:
            return data
        message = data["choices"][0]["message"]
        text = message["content"]
        self.request_local.original_content = text
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            envelope = json.loads(stripped, object_pairs_hook=unique_object)
        except ValueError:
            # Preserve malformed text for the existing application repair path;
            # usage must still be accounted for before program validation fails.
            return data
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"programs"}
            or not isinstance(envelope["programs"], dict)
            or set(envelope["programs"]) != set(expected)
        ):
            return data
        programs = []
        for index, key in enumerate(expected):
            try:
                program = Program.model_validate(envelope["programs"][key])
            except ValueError:
                return data
            programs.append({"index": index, **program.model_dump()})
        message["content"] = json.dumps({"programs": programs})
        return data

    def _response_received(self, data: dict[str, Any], record: dict[str, Any]) -> None:
        super()._response_received(data, record)
        if getattr(self.request_local, "structured_expected", None) is not None:
            record["requested_wire_format"] = "keyed-json-schema"
            record["raw_model_content"] = self.request_local.original_content
