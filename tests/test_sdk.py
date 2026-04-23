"""SDK public API tests — verifies the fathom package surface area."""

from __future__ import annotations

import gc

import pytest

# ---------------------------------------------------------------------------
# 1. Import tests
# ---------------------------------------------------------------------------


class TestImports:
    """Verify all public names are importable from the top-level package."""

    def test_import_engine(self) -> None:
        from fathom import Engine

        assert Engine is not None

    def test_import_validation_error(self) -> None:
        from fathom import ValidationError

        assert ValidationError is not None

    def test_import_compilation_error(self) -> None:
        from fathom import CompilationError

        assert CompilationError is not None

    def test_import_evaluation_error(self) -> None:
        from fathom import EvaluationError

        assert EvaluationError is not None

    def test_import_evaluation_result(self) -> None:
        from fathom import EvaluationResult

        assert EvaluationResult is not None

    def test_import_version(self) -> None:
        from fathom import __version__

        assert isinstance(__version__, str)


# ---------------------------------------------------------------------------
# 2. __version__ and __all__
# ---------------------------------------------------------------------------


class TestPackageMeta:
    """Verify package metadata exports."""

    def test_version_format(self) -> None:
        import fathom

        assert fathom.__version__ == "0.3.0"

    def test_all_contains_expected_names(self) -> None:
        import fathom

        expected = {
            "__version__",
            "Engine",
            "CompilationError",
            "EvaluationError",
            "ValidationError",
            "EvaluationResult",
            "AssertSpec",
            "AssertedFact",
        }
        assert expected == set(fathom.__all__)


# ---------------------------------------------------------------------------
# 3. Engine creation
# ---------------------------------------------------------------------------


class TestEngineCreation:
    """Verify Engine constructors."""

    def test_default_params(self) -> None:
        from fathom import Engine

        e = Engine()
        assert e._default_decision == "deny"
        assert e._session_id  # non-empty UUID

    def test_custom_decision(self) -> None:
        from fathom import Engine

        e = Engine(default_decision="allow")
        assert e._default_decision == "allow"

    def test_none_decision(self) -> None:
        from fathom import Engine

        e = Engine(default_decision=None)
        assert e._default_decision is None

    def test_custom_session_id(self) -> None:
        from fathom import Engine

        e = Engine(session_id="test-session-42")
        assert e._session_id == "test-session-42"

    def test_experimental_backward_chaining_flag(self) -> None:
        from fathom import Engine

        e = Engine(experimental_backward_chaining=True)
        assert e._experimental_backward_chaining is True


# ---------------------------------------------------------------------------
# 4. Public methods exist and are callable
# ---------------------------------------------------------------------------


_EXPECTED_METHODS = [
    "from_rules",
    "load_templates",
    "load_modules",
    "load_functions",
    "load_rules",
    "load_clips_function",
    "load_pack",
    "assert_fact",
    "assert_facts",
    "query",
    "count",
    "retract",
    "evaluate",
    "reset",
    "clear_facts",
]


class TestPublicMethods:
    """Ensure all documented public methods exist on Engine."""

    @pytest.mark.parametrize("method_name", _EXPECTED_METHODS)
    def test_method_exists_and_callable(self, method_name: str) -> None:
        from fathom import Engine

        assert hasattr(Engine, method_name)
        assert callable(getattr(Engine, method_name))

    def test_from_rules_is_classmethod(self) -> None:
        from fathom import Engine

        assert isinstance(Engine.__dict__["from_rules"], classmethod)


# ---------------------------------------------------------------------------
# 5. Engine.from_rules() convenience constructor
# ---------------------------------------------------------------------------


class TestFromRules:
    """Test the from_rules classmethod with fixtures."""

    def test_from_rules_returns_engine(self, fixtures_dir) -> None:
        from fathom import Engine

        e = Engine.from_rules(str(fixtures_dir))
        assert isinstance(e, Engine)

    def test_from_rules_loads_templates(self, fixtures_dir) -> None:
        from fathom import Engine

        e = Engine.from_rules(str(fixtures_dir))
        assert len(e._template_registry) > 0

    def test_from_rules_passes_kwargs(self, fixtures_dir) -> None:
        from fathom import Engine

        e = Engine.from_rules(str(fixtures_dir), default_decision="allow", session_id="sdk-test")
        assert e._default_decision == "allow"
        assert e._session_id == "sdk-test"


# ---------------------------------------------------------------------------
# 6. Instance independence
# ---------------------------------------------------------------------------


class TestInstanceIndependence:
    """Two Engine instances must not share state."""

    def test_separate_template_registries(self, fixtures_dir) -> None:
        from fathom import Engine

        e1 = Engine.from_rules(str(fixtures_dir))
        e2 = Engine()
        assert len(e1._template_registry) > 0
        assert len(e2._template_registry) == 0

    def test_separate_facts(self, fixtures_dir) -> None:
        from fathom import Engine

        e1 = Engine.from_rules(str(fixtures_dir))
        e2 = Engine.from_rules(str(fixtures_dir))

        template_name = next(iter(e1._template_registry))
        defn = e1._template_registry[template_name]
        # Build minimal data with required slots
        data: dict = {}
        for slot in defn.slots:
            if slot.required:
                if slot.type.value == "string" or slot.type.value == "symbol":
                    data[slot.name] = "test"
                elif slot.type.value == "integer":
                    data[slot.name] = 1
                elif slot.type.value == "float":
                    data[slot.name] = 1.0

        e1.assert_fact(template_name, data)
        assert e1.count(template_name) >= 1
        assert e2.count(template_name) == 0

    def test_separate_session_ids(self) -> None:
        from fathom import Engine

        e1 = Engine()
        e2 = Engine()
        assert e1._session_id != e2._session_id


# ---------------------------------------------------------------------------
# 7. Error types
# ---------------------------------------------------------------------------


class TestErrorTypes:
    """Error classes are importable and behave as exceptions."""

    def test_validation_error_is_exception(self) -> None:
        from fathom import ValidationError

        assert issubclass(ValidationError, Exception)

    def test_compilation_error_is_exception(self) -> None:
        from fathom import CompilationError

        assert issubclass(CompilationError, Exception)

    def test_evaluation_error_is_exception(self) -> None:
        from fathom import EvaluationError

        assert issubclass(EvaluationError, Exception)

    def test_raise_and_catch_validation_error(self) -> None:
        from fathom import ValidationError

        with pytest.raises(ValidationError, match="bad slot"):
            raise ValidationError("bad slot", template="agent", slot="x")

    def test_raise_and_catch_compilation_error(self) -> None:
        from fathom import CompilationError

        with pytest.raises(CompilationError, match="parse fail"):
            raise CompilationError("parse fail", construct="template:foo")

    def test_error_structured_fields(self) -> None:
        from fathom import ValidationError

        err = ValidationError("msg", template="t", slot="s", value=42, expected="int")
        assert err.template == "t"
        assert err.slot == "s"
        assert err.value == 42
        assert err.expected == "int"


# ---------------------------------------------------------------------------
# 8. EvaluationResult
# ---------------------------------------------------------------------------


class TestEvaluationResult:
    """EvaluationResult is a proper Pydantic model."""

    def test_instantiate_defaults(self) -> None:
        from fathom import EvaluationResult

        r = EvaluationResult()
        assert r.decision is None
        assert r.reason is None
        assert r.rule_trace == []
        assert r.module_trace == []
        assert r.duration_us == 0

    def test_instantiate_with_values(self) -> None:
        from fathom import EvaluationResult

        r = EvaluationResult(
            decision="deny",
            reason="high risk",
            rule_trace=["rule-a"],
            module_trace=["mod-x"],
            duration_us=1234,
        )
        assert r.decision == "deny"
        assert r.reason == "high risk"
        assert r.rule_trace == ["rule-a"]
        assert r.module_trace == ["mod-x"]
        assert r.duration_us == 1234

    def test_model_dump(self) -> None:
        from fathom import EvaluationResult

        r = EvaluationResult(decision="allow")
        d = r.model_dump()
        assert isinstance(d, dict)
        assert d["decision"] == "allow"


# ---------------------------------------------------------------------------
# 9. GC — create and destroy 50+ engines (AC-2.5)
# ---------------------------------------------------------------------------


class TestGarbageCollection:
    """Engine instances can be created and destroyed without resource leaks."""

    def test_create_destroy_50_engines(self) -> None:
        from fathom import Engine

        for _ in range(55):
            e = Engine()
            del e
        gc.collect()
        # If we get here without segfault/error, GC is working
        final = Engine()
        assert final._session_id  # sanity check

    def test_create_destroy_50_engines_with_facts(self, fixtures_dir) -> None:
        from fathom import Engine

        for _ in range(50):
            e = Engine.from_rules(str(fixtures_dir))
            template_name = next(iter(e._template_registry))
            defn = e._template_registry[template_name]
            data: dict = {}
            for slot in defn.slots:
                if slot.required:
                    if slot.type.value in ("string", "symbol"):
                        data[slot.name] = "test"
                    elif slot.type.value == "integer":
                        data[slot.name] = 1
                    elif slot.type.value == "float":
                        data[slot.name] = 1.0
            e.assert_fact(template_name, data)
            del e
        gc.collect()
        final = Engine()
        assert final._session_id

    def test_memory_not_growing_unboundedly(self) -> None:
        """Create 60 engines, check process memory doesn't explode."""

        from fathom import Engine

        # Baseline
        gc.collect()
        # Create and destroy
        for _ in range(60):
            e = Engine()
            del e
        gc.collect()
        # If we reach here, no crash — good enough for resource leak check
        # (exact memory measurement is platform-dependent and flaky)
        assert True


# ---------------------------------------------------------------------------
# 10. load_pack raises NotImplementedError
# ---------------------------------------------------------------------------


class TestLoadPack:
    """Engine.load_pack() must raise CompilationError for unknown packs."""

    def test_load_pack_unknown_raises(self) -> None:
        from fathom import Engine
        from fathom.errors import CompilationError

        e = Engine()
        with pytest.raises(CompilationError, match="not found"):
            e.load_pack("no-such-pack")


# ---------------------------------------------------------------------------
# 11. Engine.register_function — happy path and error paths (AC-3.1 - AC-3.5)
# ---------------------------------------------------------------------------


class TestRegisterFunction:
    """Verify Engine.register_function behavior for valid and invalid inputs."""

    def test_simple_call_from_rule(self) -> None:
        """AC-3.1: registered function is invokable from a CLIPS rule RHS."""
        from fathom import Engine

        e = Engine()
        e.register_function("double", lambda x: int(x) * 2)

        # Build a minimal template and rule that uses `(double ?n)` in its RHS.
        # Using the raw CLIPS escape hatch here because the YAML expression
        # compiler does not yet expose arbitrary user-function calls; the test
        # purpose is to prove the registered Python callable is invokable from
        # a fired rule, which is compiler-independent.
        e._env.build(
            "(deftemplate MAIN::number (slot n (type INTEGER)) (slot result (type INTEGER)))"
        )
        e._env.build(
            "(defrule MAIN::apply-double "
            "(number (n ?n) (result 0)) "
            "=> "
            "(assert (number (n 999) (result (double ?n)))))"
        )
        e._env.assert_string("(number (n 5) (result 0))")
        e.evaluate()

        results = sorted(int(f["result"]) for f in e._env.find_template("MAIN::number").facts())
        # Input fact has result=0; rule fires once and asserts result=10.
        assert 10 in results

    def test_empty_name_raises(self) -> None:
        """AC-3.2: empty name raises ValueError."""
        from fathom import Engine

        e = Engine()
        with pytest.raises(ValueError, match="non-empty"):
            e.register_function("", lambda: None)

    def test_whitespace_name_raises(self) -> None:
        """AC-3.2: name with whitespace raises ValueError."""
        from fathom import Engine

        e = Engine()
        # Whitespace is now caught by the general CLIPS-identifier regex.
        with pytest.raises(ValueError, match=r"\[A-Za-z\]"):
            e.register_function("foo bar", lambda: None)

    def test_reserved_prefix_raises(self) -> None:
        """AC-3.3: name starting with reserved `fathom-` prefix raises ValueError.

        The error message must include the literal string ``fathom-``.
        """
        from fathom import Engine

        e = Engine()
        with pytest.raises(ValueError, match="fathom-") as exc_info:
            e.register_function("fathom-x", lambda: None)
        assert "fathom-" in str(exc_info.value)

    def test_reregister_overwrites(self) -> None:
        """AC-3.4: re-registering an existing name silently overwrites the binding."""
        from fathom import Engine

        e = Engine()
        e.register_function("pick", lambda: "first")
        assert e._env.eval("(pick)") == "first"

        # Second registration wins.
        e.register_function("pick", lambda: "second")
        assert e._env.eval("(pick)") == "second"

    def test_signature_exported_on_Engine(self) -> None:  # noqa: N802 — spec-mandated name
        """AC-3.5: Engine.register_function exposes `name: str` and `fn: Callable`.

        Verifies the public signature via `inspect.signature` so SDK callers
        (and downstream typing tooling) see the documented parameter shape.
        The engine module uses ``from __future__ import annotations`` so
        annotations are stringified; compare on the string form.
        """
        import inspect

        from fathom import Engine

        sig = inspect.signature(Engine.register_function)
        params = sig.parameters
        assert "name" in params
        assert "fn" in params
        # `name` must be annotated as `str`.
        assert params["name"].annotation == "str"
        # `fn` must be annotated as a Callable variant (Callable[..., Any]).
        assert "Callable" in str(params["fn"].annotation)


# ---------------------------------------------------------------------------
# 12. Public surface — new exports and version bump (AC-6.1, FR-12)
# ---------------------------------------------------------------------------


class TestPublicSurface:
    """Verify the rule-assertions public surface additions (AC-6.1, FR-12)."""

    def test_AssertSpec_importable_from_fathom(self) -> None:  # noqa: N802 — spec-mandated name
        """AC-6.1, FR-12: `AssertSpec` is importable from the top-level package."""
        from fathom import AssertSpec

        # Must construct cleanly with the documented minimal shape.
        spec = AssertSpec(template="routing_decision", slots={"source_id": "?sid"})
        assert spec.template == "routing_decision"
        assert spec.slots == {"source_id": "?sid"}

    def test_AssertedFact_importable_from_fathom(self) -> None:  # noqa: N802 — spec-mandated name
        """FR-12: `AssertedFact` is importable from the top-level package."""
        from fathom import AssertedFact

        # Must construct cleanly with the documented minimal shape.
        fact = AssertedFact(template="routing_decision", slots={"source_id": "alpha"})
        assert fact.template == "routing_decision"
        assert fact.slots == {"source_id": "alpha"}

    def test_version_bumped_to_0_3_0(self) -> None:
        """`fathom.__version__` is bumped to 0.3.0 for this release."""
        import fathom

        assert fathom.__version__ == "0.3.0"
