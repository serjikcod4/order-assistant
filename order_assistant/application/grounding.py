import re
import threading
import unicodedata
from collections.abc import Callable
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from order_assistant.application.clarifications import QUESTION_BY_CODE
from order_assistant.application.ports import OrderExtractor
from order_assistant.domain import (
    Brand,
    ExtractedOrder,
    GroundingIssue,
    GroundingIssueCode,
    GroundingResult,
)


SUPPORTED_BRANDS = tuple(brand.value for brand in Brand)
GROUNDING_GUARD_VERSION = "grounding-v1"
UNSUPPORTED_BRAND_EXCLUSIONS = {"SKU", "UAH", "ISO", *SUPPORTED_BRANDS}
NUMBER_PATTERN = re.compile(
    r"(?<!\w)(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?(?!\w)"
)
TIME_PATTERN = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
ISO_DEADLINE_PATTERN = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:T|\s+(?:в\s+)?)(\d{2}):(\d{2})"
    r"(?::(\d{2}))?(Z|[+-]\d{2}:\d{2})?(?!\d)"
)
LOCAL_DEADLINE_PATTERN = re.compile(
    r"(?<!\d)(\d{2})\.(\d{2})\.(\d{4})[ ,T]+(\d{2}):(\d{2})(?!\d)"
)

def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"[‐‑‒–—−]", "-", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _grounded_token(source: str, value: str) -> bool:
    source = _normalize(source).casefold()
    value = _normalize(value).casefold()
    parts = [part for part in re.split(r"[\s-]+", value) if part]
    if not parts:
        return False
    pattern = r"(?<!\w)" + r"[\s-]*".join(map(re.escape, parts)) + r"(?!\w)"
    return re.search(pattern, source) is not None


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except InvalidOperation:
        return None


def _number_occurrences(source: str, value: int | Decimal) -> list[tuple[int, int]]:
    expected = Decimal(str(value))
    result = []
    for match in NUMBER_PATTERN.finditer(_normalize(source)):
        parsed = _decimal(match.group())
        if parsed == expected:
            result.append(match.span())
    return result


def _context(source: str, span: tuple[int, int], radius: int = 24) -> str:
    normalized = _normalize(source).casefold()
    start, end = span
    return normalized[max(0, start - radius) : min(len(normalized), end + radius)]


def _quantity_grounded(source: str, value: int) -> bool:
    quantity_markers = (
        "шт",
        "штук",
        "одиниц",
        "нужно",
        "нужны",
        "потрібно",
        "требуется",
        "підшип",
        "подшип",
        *[brand.casefold() for brand in SUPPORTED_BRANDS],
    )
    normalized = _normalize(source).casefold()
    for span in _number_occurrences(source, value):
        start, end = span
        before = normalized[max(0, start - 20) : start]
        after = normalized[end : min(len(normalized), end + 20)]
        price_prefix = re.search(
            r"(?:до|максимум|цена|ціна|не дороже|не дорожче)\s*$", before
        )
        price_suffix = re.match(r"\s*(?:грн|₴)", after) or any(
            marker in after for marker in ("за шту", "за одиниц")
        )
        if price_prefix or price_suffix:
            continue
        context = before + normalized[start:end] + after
        if any(marker in context for marker in quantity_markers):
            return True
    return False


def _price_grounded(source: str, value: Decimal) -> bool:
    price_markers = (
        "грн",
        "₴",
        "за шту",
        "за одиниц",
        "цена",
        "ціна",
        "не дороже",
        "не дорожче",
        "максимум",
    )
    budget_markers = ("бюджет", "всего", "загальний бюджет")
    for span in _number_occurrences(source, value):
        context = _context(source, span, radius=32)
        if any(marker in context for marker in budget_markers):
            continue
        if any(marker in context for marker in price_markers):
            return True
    return False


def _source_brand_tokens(source: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", source)
    return {
        token
        for token in re.findall(r"(?<![A-Za-z])[A-Z]{2,10}(?![A-Za-z])", normalized)
        if token not in UNSUPPORTED_BRAND_EXCLUSIONS
    }


def _timezone(offset: str | None, default) -> timezone:
    if not offset or offset == "Z":
        return timezone.utc if offset == "Z" else default
    sign = 1 if offset[0] == "+" else -1
    hours, minutes = map(int, offset[1:].split(":"))
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _exact_deadline(source: str, received_at: datetime) -> datetime | None:
    normalized = _normalize(source)
    iso = ISO_DEADLINE_PATTERN.search(normalized)
    if iso:
        year, month, day, hour, minute, second, offset = iso.groups()
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second or 0),
            tzinfo=_timezone(offset, received_at.tzinfo or timezone.utc),
        )
    local = LOCAL_DEADLINE_PATTERN.search(normalized)
    if local:
        day, month, year, hour, minute = map(int, local.groups())
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=received_at.tzinfo or timezone.utc,
        )
    lowered = normalized.casefold()
    if "завтра" in lowered:
        match = TIME_PATTERN.search(lowered)
        if match:
            tomorrow = received_at + timedelta(days=1)
            return datetime.combine(
                tomorrow.date(),
                time(int(match.group(1)), int(match.group(2))),
                tzinfo=received_at.tzinfo or timezone.utc,
            )
    return None


def _ambiguous_deadline(source: str) -> bool:
    lowered = _normalize(source).casefold()
    exact_time = TIME_PATTERN.search(lowered) is not None
    return (
        ("завтра утром" in lowered or "завтра вранці" in lowered)
        and not exact_time
    ) or "в ближайшее время" in lowered


def _issue(
    code: GroundingIssueCode,
    field: str | None = None,
    actual: object | None = None,
    expected: str | None = None,
) -> GroundingIssue:
    return GroundingIssue(
        code=code,
        field=field,
        actual=None if actual is None else str(actual),
        expected=expected,
    )


class ExtractionGroundingGuard:
    """Reject values that cannot be conservatively grounded in source text."""

    def guard(
        self,
        source_text: str,
        candidate: ExtractedOrder,
        received_at: datetime,
    ) -> GroundingResult:
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware.")

        updates: dict[str, object] = {}
        issues: list[GroundingIssue] = []

        if candidate.model and not _grounded_token(source_text, candidate.model):
            updates["model"] = None
            issues.append(
                _issue(
                    GroundingIssueCode.UNGROUNDED_MODEL,
                    "model",
                    candidate.model,
                    "value present in source text",
                )
            )

        primary = candidate.primary_brand
        if primary and not _grounded_token(source_text, primary.value):
            updates["primary_brand"] = None
            primary = None
            issues.append(
                _issue(
                    GroundingIssueCode.UNGROUNDED_PRIMARY_BRAND,
                    "primary_brand",
                    candidate.primary_brand.value,
                    "brand present as a complete token",
                )
            )

        unsupported = sorted(_source_brand_tokens(source_text))
        if unsupported:
            issues.append(
                _issue(
                    GroundingIssueCode.UNSUPPORTED_BRAND,
                    "primary_brand",
                    ", ".join(unsupported),
                    ", ".join(SUPPORTED_BRANDS),
                )
            )

        grounded_fallbacks = []
        for brand in candidate.fallback_brands:
            grounded = _grounded_token(source_text, brand.value)
            duplicate = primary is not None and brand == primary
            if grounded and not duplicate:
                grounded_fallbacks.append(brand)
                continue
            issues.append(
                _issue(
                    GroundingIssueCode.UNGROUNDED_FALLBACK_BRAND,
                    "fallback_brands",
                    brand.value,
                    "explicit fallback distinct from primary brand",
                )
            )
        if grounded_fallbacks != candidate.fallback_brands:
            updates["fallback_brands"] = grounded_fallbacks

        if candidate.quantity is not None and not _quantity_grounded(
            source_text, candidate.quantity
        ):
            updates["quantity"] = None
            issues.append(
                _issue(
                    GroundingIssueCode.UNGROUNDED_QUANTITY,
                    "quantity",
                    candidate.quantity,
                    "quantity with explicit context",
                )
            )

        if candidate.max_unit_price is not None and not _price_grounded(
            source_text, candidate.max_unit_price
        ):
            updates["max_unit_price"] = None
            issues.append(
                _issue(
                    GroundingIssueCode.UNGROUNDED_PRICE,
                    "max_unit_price",
                    candidate.max_unit_price,
                    "unit price with explicit context",
                )
            )

        exact_deadline = _exact_deadline(source_text, received_at)
        if _ambiguous_deadline(source_text):
            updates["delivery_deadline"] = None
            issues.append(
                _issue(
                    GroundingIssueCode.AMBIGUOUS_DELIVERY_DEADLINE,
                    "delivery_deadline",
                    candidate.delivery_deadline,
                    "exact date and time",
                )
            )
        elif exact_deadline is not None:
            updates["delivery_deadline"] = exact_deadline
        elif candidate.delivery_deadline is not None:
            updates["delivery_deadline"] = None
            issues.append(
                _issue(
                    GroundingIssueCode.AMBIGUOUS_DELIVERY_DEADLINE,
                    "delivery_deadline",
                    candidate.delivery_deadline,
                    "supported explicit deadline",
                )
            )

        if candidate.clarification_questions:
            issues.append(
                _issue(
                    GroundingIssueCode.UNSAFE_CLARIFICATION_CONTENT,
                    "clarification_questions",
                    "[discarded untrusted output]",
                    "deterministic templates",
                )
            )

        partially_guarded = candidate.model_copy(
            update={**updates, "clarification_questions": []}
        )
        missing_codes = (
            ("model", GroundingIssueCode.MISSING_MODEL),
            ("quantity", GroundingIssueCode.MISSING_QUANTITY),
            ("primary_brand", GroundingIssueCode.MISSING_PRIMARY_BRAND),
            ("max_unit_price", GroundingIssueCode.MISSING_PRICE),
            ("delivery_deadline", GroundingIssueCode.MISSING_DELIVERY_DEADLINE),
        )
        existing_codes = {issue.code for issue in issues}
        for field, code in missing_codes:
            if getattr(partially_guarded, field) is None and code not in existing_codes:
                issues.append(_issue(code, field))

        question_codes = [issue.code for issue in issues]
        questions = list(
            dict.fromkeys(
                QUESTION_BY_CODE[code]
                for code in question_codes
                if code in QUESTION_BY_CODE
            )
        )
        guarded = partially_guarded.model_copy(
            update={
                "clarification_questions": questions,
                "requires_clarification": bool(questions),
            }
        )
        return GroundingResult(
            extracted=guarded,
            issues=issues,
            changed=guarded != candidate,
        )


class GroundedOrderExtractor:
    """Apply deterministic grounding to one explicitly untrusted extractor."""

    def __init__(
        self,
        extractor: OrderExtractor,
        guard: ExtractionGroundingGuard,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.extractor = extractor
        self.guard = guard
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._local = threading.local()

    @property
    def last_grounding_result(self) -> GroundingResult | None:
        return getattr(self._local, "grounding_result", None)

    def extract(self, customer_message: str) -> ExtractedOrder:
        candidate = self.extractor.extract(customer_message)
        result = self.guard.guard(customer_message, candidate, self.clock())
        self._local.grounding_result = result
        return result.extracted

    def close(self) -> None:
        close = getattr(self.extractor, "close", None)
        if close is not None:
            close()
