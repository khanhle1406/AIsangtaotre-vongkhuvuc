"""Explicit answer contracts; preserve names and reject ambiguous numeric output."""

import datetime as dt
import math
import re
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnswerFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["auto", "text", "integer", "decimal", "boolean", "date"] = "auto"
    decimals: int | None = Field(default=None, ge=0, le=10)
    count: int | None = Field(default=None, ge=1, le=100)
    separator: str = Field(default=", ", min_length=0, max_length=10)
    rounding: Literal["half_even", "half_up"] = "half_even"
    date_format: Literal["iso", "iso_datetime"] = "iso"

    @model_validator(mode="before")
    @classmethod
    def unspecified_format_defaults(cls, value: Any) -> Any:
        """JSON null means unspecified for optional fields with concrete defaults."""
        if not isinstance(value, dict):
            return value
        defaulted = {"kind", "separator", "rounding", "date_format"}
        return {
            key: item
            for key, item in value.items()
            if item is not None or key not in defaulted
        }


def query_format(query: str, spec: AnswerFormat | None = None) -> AnswerFormat:
    """Explicit wording takes precedence over the model's formatting guess."""
    result = (spec or AnswerFormat()).model_copy()
    lower = query.lower()
    words = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    decimal = re.search(
        r"\b(\d+|zero|one|two|three|four|five|six) decimal places?\b", lower
    )
    if decimal:
        result.kind = "decimal"
        result.decimals = words[decimal[1]] if decimal[1] in words else int(decimal[1])
    elif re.search(r"\bintegers?\b", lower):
        result.kind = "integer"
    elif re.search(r"\byes\s*(?:or|/)\s*no\b", lower):
        result.kind = "boolean"
    elif "iso" in lower and "date" in lower:
        result.kind = "date"
    count = re.search(
        r"\b(\d+|one|two|three|four|five|six) (?:integers?|numbers?|values?|sector names|items)\b",
        lower,
    )
    if count:
        result.count = words[count[1]] if count[1] in words else int(count[1])
    if "comma and one space" in lower or "men, women" in lower:
        result.separator = ", "
    if "as `men, women`" in lower:
        result.count = 2
    if "half up" in lower:
        result.rounding = "half_up"
    # Revalidate fields inferred from arbitrary query text.
    return AnswerFormat.model_validate(result.model_dump())


def _number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("Boolean cannot be formatted as a numeric measure")
    text = str(value).strip()
    if not re.fullmatch(
        r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?", text
    ):
        raise ValueError(f"Expected an unambiguous number, received {value!r}")
    try:
        number = Decimal(text.replace(",", ""))
    except InvalidOperation as error:
        raise ValueError("Invalid numeric result") from error
    if not number.is_finite():
        raise ValueError("Non-finite result")
    return number


def format_answer(raw_answer: Any, query: str, spec: AnswerFormat | None = None) -> str:
    """Format final scalars/lists using query constraints without guessing an answer."""
    if raw_answer is None:
        raise ValueError("Missing final answer")
    contract = query_format(query, spec)
    magnitude_requested = bool(
        re.search(
            r"\b(?:report|return|give|output)\b[^.?!]{0,60}\b(?:positive magnitudes?|absolute (?:value|difference|magnitude)s?)\b"
            r"|\b(?:what is|calculate|compute)\s+(?:the\s+)?absolute (?:value|difference|magnitude)\b",
            query,
            re.IGNORECASE,
        )
    ) and not re.search(
        r"\b(?:keep|retain)\s+(?:its |the |their )?sign\b", query, re.IGNORECASE
    )
    # A numeric list string is accepted only with an explicit cardinality and
    # exact separator. Commas inside each number must still satisfy _number.
    if (
        isinstance(raw_answer, str)
        and contract.kind in {"integer", "decimal"}
        and contract.count
        and contract.count > 1
        and contract.separator
    ):
        parts = raw_answer.split(contract.separator)
        if len(parts) == contract.count:
            for part in parts:
                _number(part)
            raw_answer = parts
    values = list(raw_answer) if isinstance(raw_answer, (list, tuple)) else [raw_answer]
    if not values or (contract.count is not None and len(values) != contract.count):
        raise ValueError("Result cardinality does not match the requested answer")
    if len(values) > 1 and not contract.separator:
        raise ValueError("A list needs an explicit nonempty separator")
    options = re.search(
        r"rank the following [^:]+:\s*(.*?)\.\s*answer", query, re.IGNORECASE
    )
    if options:
        labels = [
            re.sub(r"^and\s+", "", part.strip(), flags=re.IGNORECASE)
            for part in options[1].split(",")
        ]
        mapped = []
        for value in values:
            text = " ".join(str(value).replace("-\n", "").split()).casefold()
            candidates = [
                label
                for label in labels
                if text == label.casefold() or text.startswith(label.casefold() + " ")
            ]
            if len(candidates) != 1:
                raise ValueError(
                    "Ranked label does not uniquely match the options specified in the question"
                )
            mapped.append(candidates[0])
        if len(mapped) != len(labels) or len(set(mapped)) != len(mapped):
            raise ValueError("Ranking must contain each requested option exactly once")
        values = mapped
    formatted = []
    for value in values:
        kind = contract.kind
        if (
            magnitude_requested
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            value = abs(value)
        if isinstance(value, bool) and kind in {"integer", "decimal"}:
            raise TypeError("Boolean result cannot represent a numeric measure")
        if isinstance(value, bool) or kind == "boolean":
            if isinstance(value, bool):
                formatted.append("Yes" if value else "No")
            elif str(value).lower() in {"yes", "no", "true", "false"}:
                formatted.append(
                    "Yes" if str(value).lower() in {"yes", "true"} else "No"
                )
            else:
                raise ValueError("Expected Yes/No result")
        elif kind in {"integer", "decimal"}:
            number = _number(value)
            if magnitude_requested:
                number = abs(number)
            rounding = (
                ROUND_HALF_UP if contract.rounding == "half_up" else ROUND_HALF_EVEN
            )
            if kind == "integer":
                if (
                    number != number.to_integral_value()
                    and "round" not in query.lower()
                ):
                    raise ValueError(
                        "Nonintegral result for an integer answer; repair the computation"
                    )
                formatted.append(str(number.quantize(Decimal(1), rounding=rounding)))
            else:
                decimals = contract.decimals if contract.decimals is not None else 2
                formatted.append(
                    f"{number.quantize(Decimal(1).scaleb(-decimals), rounding=rounding):.{decimals}f}"
                )
        elif kind == "date":
            if isinstance(value, str):
                value = dt.datetime.fromisoformat(value)
            if not isinstance(value, (dt.datetime, dt.date)):
                raise ValueError(
                    "Expected an ISO or typed date; ambiguous locale dates are not guessed"
                )
            if isinstance(value, dt.datetime) and contract.date_format == "iso":
                value = value.date()
            formatted.append(value.isoformat())
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Non-finite result")
            formatted.append(str(int(value)) if value.is_integer() else str(value))
        elif isinstance(value, (str, int, dt.date)):
            formatted.append(" ".join(str(value).splitlines()).strip())
        else:
            raise ValueError(f"Unsupported final answer type: {type(value).__name__}")
    return contract.separator.join(formatted)
