"""FactManager — validates and asserts facts into CLIPS working memory."""

from __future__ import annotations

import difflib
import time
from typing import TYPE_CHECKING, Any

import clips

from fathom.errors import ValidationError
from fathom.models import SlotType

if TYPE_CHECKING:
    from collections.abc import Callable

    from fathom.models import TemplateDefinition

# Python type → SlotType mapping for validation
_PYTHON_TYPE_MAP: dict[SlotType, tuple[type, ...]] = {
    SlotType.STRING: (str,),
    SlotType.SYMBOL: (str,),
    SlotType.FLOAT: (float, int),
    SlotType.INTEGER: (int,),
}


class FactManager:
    """Validates and asserts facts into CLIPS working memory."""

    def __init__(
        self,
        env_provider: Callable[[], clips.Environment],
        template_registry: dict[str, TemplateDefinition],
    ) -> None:
        self._env_provider = env_provider
        self._template_registry = template_registry
        self._ttl_config: dict[str, int] = {}
        self._fact_timestamps: dict[int, float] = {}

    # --- Public API ---

    def set_ttl(self, template: str, seconds: int) -> None:
        """Configure TTL (in seconds) for facts of the given template."""
        self._ttl_config[template] = seconds

    def _assert_validated(
        self,
        env: clips.Environment,
        template_name: str,
        validated: dict[str, Any],
    ) -> None:
        """Coerce + assert a pre-validated slot dict, recording the timestamp."""
        coerced = self._coerce_for_clips(template_name, validated)
        tpl = env.find_template(template_name)
        try:
            fact = tpl.assert_fact(**coerced)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(
                f"CLIPS assertion failed for '{template_name}': {exc}",
                template=template_name,
            ) from exc
        self._fact_timestamps[fact.index] = time.time()

    def assert_fact(self, template_name: str, data: dict[str, Any]) -> None:
        """Validate and assert a single fact into working memory."""
        env = self._env_provider()
        validated = self._validate(template_name, data)
        self._assert_validated(env, template_name, validated)

    def assert_facts(self, facts: list[tuple[str, dict[str, Any]]]) -> None:
        """Assert multiple facts atomically (pre-validate all, then assert)."""
        env = self._env_provider()
        validated_batch = [
            (template_name, self._validate(template_name, data)) for template_name, data in facts
        ]
        for template_name, validated in validated_batch:
            self._assert_validated(env, template_name, validated)

    def query(
        self,
        template_name: str,
        fact_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query working memory for facts matching template and optional filter."""
        env = self._env_provider()
        template_def = self._template_registry.get(template_name)
        if template_def is None:
            raise ValidationError(
                f"Unknown template '{template_name}'",
                template=template_name,
            )
        tpl = env.find_template(template_name)
        slot_names = [s.name for s in template_def.slots]
        results: list[dict[str, Any]] = []
        for fact in tpl.facts():
            row: dict[str, Any] = {}
            for name in slot_names:
                val = fact[name]
                # Convert CLIPS Symbol back to plain str
                if isinstance(val, clips.Symbol):
                    val = str(val)
                row[name] = val
            # Apply filter
            if fact_filter:
                if all(row.get(k) == v for k, v in fact_filter.items()):
                    results.append(row)
            else:
                results.append(row)
        return results

    def count(
        self,
        template_name: str,
        fact_filter: dict[str, Any] | None = None,
    ) -> int:
        """Count facts matching template and optional filter."""
        return len(self.query(template_name, fact_filter))

    def retract(
        self,
        template_name: str,
        fact_filter: dict[str, Any] | None = None,
    ) -> int:
        """Retract matching facts from working memory. Returns count retracted."""
        env = self._env_provider()
        template_def = self._template_registry.get(template_name)
        if template_def is None:
            raise ValidationError(
                f"Unknown template '{template_name}'",
                template=template_name,
            )
        tpl = env.find_template(template_name)
        slot_names = [s.name for s in template_def.slots]
        count = 0
        # Collect facts first to avoid mutating during iteration
        to_retract = []
        for fact in tpl.facts():
            row: dict[str, Any] = {}
            for name in slot_names:
                val = fact[name]
                if isinstance(val, clips.Symbol):
                    val = str(val)
                row[name] = val
            if fact_filter:
                if all(row.get(k) == v for k, v in fact_filter.items()):
                    to_retract.append(fact)
            else:
                to_retract.append(fact)
        for fact in to_retract:
            fact.retract()
            count += 1
        return count

    def clear_all(self) -> None:
        """Clear all user facts from working memory.

        Retracts all facts from registered templates but leaves
        internal CLIPS facts (initial-fact, __fathom_decision) untouched.
        """
        for template_name in list(self._template_registry):
            self.retract(template_name)

    def clear_timestamps(self) -> None:
        """Drop all tracked TTL timestamps.

        Called on engine reset so indices from the previous reset boundary
        do not mis-attribute to newly-asserted facts.
        """
        self._fact_timestamps.clear()

    def cleanup_expired(self) -> int:
        """Retract facts whose TTL has expired. Returns count retracted."""
        env = self._env_provider()
        now = time.time()
        retracted = 0
        for template_name, ttl in self._ttl_config.items():
            tpl = env.find_template(template_name)
            to_retract = []
            for fact in tpl.facts():
                ts = self._fact_timestamps.get(fact.index)
                if ts is not None and ts + ttl < now:
                    to_retract.append(fact)
            for fact in to_retract:
                fact.retract()
                self._fact_timestamps.pop(fact.index, None)
                retracted += 1
        return retracted

    # --- CLIPS coercion ---

    def _coerce_for_clips(self, template_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Python values to CLIPS-native types (e.g. str → Symbol)."""
        template = self._template_registry[template_name]
        slot_map = {s.name: s for s in template.slots}
        result = dict(data)
        for key, value in result.items():
            slot = slot_map.get(key)
            if slot is None:
                continue
            if slot.type == SlotType.SYMBOL and isinstance(value, str):
                result[key] = clips.Symbol(value)
        return result

    # --- Validation chain ---

    def _validate(self, template_name: str, data: dict[str, Any]) -> dict[str, Any]:
        """Full validation chain. Returns validated data with defaults applied."""
        # 1. Check template exists
        template = self._template_registry.get(template_name)
        if template is None:
            raise ValidationError(
                f"Unknown template '{template_name}'",
                template=template_name,
            )

        # 2. Check unknown slots
        self._check_unknown_slots(template, data)

        # 3. Apply defaults
        data = self._apply_defaults(template, data)

        # 4. Check required
        self._check_required(template, data)

        # 5. Coerce types (int→float, float→int, non-str→str)
        data = self._coerce_types(template, data)

        # 6. Check types
        self._check_types(template, data)

        # 7. Check allowed values
        self._check_allowed_values(template, data)

        return data

    def _check_unknown_slots(self, template: TemplateDefinition, data: dict[str, Any]) -> None:
        """Raise ValidationError if data contains slot names not in the template."""
        known_slots = {s.name for s in template.slots}
        unknown = set(data.keys()) - known_slots
        if unknown:
            # Suggest closest match for the first unknown slot
            first_unknown = sorted(unknown)[0]
            matches = difflib.get_close_matches(first_unknown, known_slots, n=1)
            suggestion = f" Did you mean '{matches[0]}'?" if matches else ""
            raise ValidationError(
                f"Unknown slot(s) {sorted(unknown)} in template '{template.name}'.{suggestion}",
                template=template.name,
                slot=first_unknown,
            )

    def _apply_defaults(
        self, template: TemplateDefinition, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a copy of data with defaults applied for missing optional slots."""
        result = dict(data)
        for slot in template.slots:
            if slot.name not in result and slot.default is not None:
                result[slot.name] = slot.default
        return result

    def _coerce_types(self, template: TemplateDefinition, data: dict[str, Any]) -> dict[str, Any]:
        """Attempt to coerce values to expected slot types."""
        slot_map = {s.name: s for s in template.slots}
        result = dict(data)
        for key, value in result.items():
            slot = slot_map.get(key)
            if slot is None:
                continue
            if (
                slot.type == SlotType.INTEGER
                and isinstance(value, float)
                and not isinstance(value, bool)
                and value == int(value)
            ):
                result[key] = int(value)
            elif slot.type == SlotType.STRING and not isinstance(value, str):
                result[key] = str(value)
        return result

    def _check_required(self, template: TemplateDefinition, data: dict[str, Any]) -> None:
        """Raise ValidationError if required slots are missing."""
        missing = [s.name for s in template.slots if s.required and s.name not in data]
        if missing:
            raise ValidationError(
                f"Missing required slot(s) {missing} in template '{template.name}'",
                template=template.name,
                slot=missing[0],
                expected="required",
            )

    def _check_types(self, template: TemplateDefinition, data: dict[str, Any]) -> None:
        """Raise ValidationError if slot values have wrong types."""
        slot_map = {s.name: s for s in template.slots}
        for key, value in data.items():
            slot = slot_map.get(key)
            if slot is None:
                continue
            expected_types = _PYTHON_TYPE_MAP.get(slot.type)
            if expected_types is None:
                continue
            # Special case: integer type should not accept bool
            if slot.type == SlotType.INTEGER and isinstance(value, bool):
                raise ValidationError(
                    f"Slot '{key}' expects {slot.type.value}, got {type(value).__name__}",
                    template=template.name,
                    slot=key,
                    value=value,
                    expected=slot.type.value,
                )
            # Special case: float type accepts int (coercion), but not bool
            if slot.type == SlotType.FLOAT and isinstance(value, bool):
                raise ValidationError(
                    f"Slot '{key}' expects {slot.type.value}, got {type(value).__name__}",
                    template=template.name,
                    slot=key,
                    value=value,
                    expected=slot.type.value,
                )
            if not isinstance(value, expected_types):
                raise ValidationError(
                    f"Slot '{key}' expects {slot.type.value}, got {type(value).__name__}",
                    template=template.name,
                    slot=key,
                    value=value,
                    expected=slot.type.value,
                )

    def _check_allowed_values(self, template: TemplateDefinition, data: dict[str, Any]) -> None:
        """Raise ValidationError if slot value is not in allowed_values."""
        slot_map = {s.name: s for s in template.slots}
        for key, value in data.items():
            slot = slot_map.get(key)
            if slot is None or slot.allowed_values is None:
                continue
            str_value = str(value)
            if str_value not in slot.allowed_values:
                raise ValidationError(
                    f"Slot '{key}' value '{value}' not in allowed values {slot.allowed_values}",
                    template=template.name,
                    slot=key,
                    value=value,
                    expected=str(slot.allowed_values),
                )
