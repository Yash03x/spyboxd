"""What the panel sweep is allowed to claim, and what it must refuse to.

A checker that quietly skips things is worse than no checker: it reports a
clean run over a shrinking surface. Most of these tests are about that failure
mode rather than about the happy path.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"


def _prepare_service_imports() -> None:
    """Make `import services` work the way the API's own process does.

    `database.connection` resolves DATABASE_URL at import time, so importing
    the package at all needs one to exist. These tests only read function
    signatures and never open a connection, and SQLAlchemy builds its engine
    lazily, so a placeholder is enough. `setdefault` so a real one -- CI's
    Postgres service -- always wins.
    """

    import os

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+psycopg://sweep:unused@127.0.0.1:1/never_connected"
    )


def _load_sweep():
    path = Path(__file__).resolve().parent / "panel_sweep.py"
    spec = importlib.util.spec_from_file_location("panel_sweep", path)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: dataclasses resolve annotations through
    # sys.modules and fail on a module that is not there yet.
    sys.modules["panel_sweep"] = module
    spec.loader.exec_module(module)
    return module


sweep_module = _load_sweep()


class FakeProfile:
    def __init__(self, username: str, identifier: int, library_size: int | None = None):
        self.username = username
        self.id = identifier
        if library_size is not None:
            self._sweep_library_size = library_size


class FakeSession:
    """Records rollbacks, and refuses to be committed."""

    def __init__(self):
        self.rollbacks = 0
        self.closed = False
        self.bind = types.SimpleNamespace(dialect=types.SimpleNamespace(name="sqlite"))

    def execute(self, *_args, **_kwargs):
        raise AssertionError("a sqlite session must not be asked to SET TRANSACTION")

    def commit(self):
        raise AssertionError("the sweep must never commit")

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _package(**functions) -> types.ModuleType:
    """A stand-in services package holding one module of the given functions."""

    package = types.ModuleType("fake_services")
    package.__path__ = []
    module = types.ModuleType("fake_services.panels")
    for name, function in functions.items():
        function.__module__ = "fake_services.panels"
        setattr(module, name, function)
    sys.modules["fake_services"] = package
    sys.modules["fake_services.panels"] = module
    package.panels = module
    return package


def _run(monkeypatch, package, excluded=None, profiles=None):
    monkeypatch.setattr(sweep_module, "EXCLUDED", excluded or {})
    monkeypatch.setitem(sys.modules, "services", package)
    session = FakeSession()
    monkeypatch.setattr(
        sweep_module,
        "discover_session_functions",
        lambda _p: sweep_module.discover_session_functions.__wrapped__(package)
        if hasattr(sweep_module.discover_session_functions, "__wrapped__")
        else _discover(package),
    )
    people = profiles if profiles is not None else [FakeProfile("alpha", 1), FakeProfile("beta", 2)]
    result = sweep_module.run_sweep(lambda: session, lambda _db: people)
    return result, session


def _discover(package):
    found = {}
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith(f"{package.__name__}."):
            continue
        short = module_name.split(".", 1)[1]
        for attribute_name, attribute in vars(module).items():
            if attribute_name.startswith("_") or not callable(attribute):
                continue
            if getattr(attribute, "__module__", None) != module_name:
                continue
            parameters = list(__import__("inspect").signature(attribute).parameters)
            if parameters and parameters[0] in {"db", "session", "db_session"}:
                found[f"{short}.{attribute_name}"] = attribute
    return found


def test_a_builder_that_raises_is_reported_rather_than_swallowed(monkeypatch) -> None:
    def build_broken(db, profiles):
        raise RuntimeError("column does not exist")

    result, _ = _run(monkeypatch, _package(build_broken=build_broken))

    assert not result.ok
    assert len(result.failures) == 1
    assert "column does not exist" in result.failures[0].error


def test_a_builder_that_reaches_the_database_unswept_fails_the_run(monkeypatch) -> None:
    """The whole point: silence must never be mistaken for coverage.

    A new function that touches the database and is neither a `build_` nor a
    named exclusion has to be classified before this passes.
    """

    def helper_touching_the_database(db, something):
        return {}

    result, _ = _run(monkeypatch, _package(helper_touching_the_database=helper_touching_the_database))

    assert not result.ok
    assert result.undeclared == ["panels.helper_touching_the_database"]


def test_an_exclusion_for_a_function_that_no_longer_exists_fails_the_run(monkeypatch) -> None:
    """A stale exclusion is a promise about code that is gone, and it would
    silently absorb the next function to take that name."""

    def build_present(db, profiles):
        return {}

    result, _ = _run(
        monkeypatch,
        _package(build_present=build_present),
        excluded={"panels.removed_last_year": "reason that outlived its function"},
    )

    assert not result.ok
    assert result.stale_exclusions == ["panels.removed_last_year"]


def test_a_slow_builder_fails_even_though_it_returned(monkeypatch) -> None:
    """The twelve-second panel returned correct data. Correct and unusable is
    still a defect, so latency is a failure and not a note."""

    def build_slow(db, profiles):
        return {}

    monkeypatch.setattr(sweep_module, "DEFAULT_BUDGET_SECONDS", -1.0)
    monkeypatch.setattr(sweep_module, "BUDGET_OVERRIDES", {})
    result, _ = _run(monkeypatch, _package(build_slow=build_slow))

    assert not result.ok
    assert result.failures[0].over_budget is True
    assert result.failures[0].error is None


def test_the_session_is_rolled_back_and_closed_even_when_a_builder_explodes(monkeypatch) -> None:
    def build_broken(db, profiles):
        raise RuntimeError("boom")

    _, session = _run(monkeypatch, _package(build_broken=build_broken))

    assert session.rollbacks >= 1
    assert session.closed is True


def test_a_single_profile_instance_is_refused_rather_than_half_swept(monkeypatch) -> None:
    """Pair builders need two profiles. Running with one would report a pass
    over a surface that was never exercised."""

    def build_anything(db, profiles):
        return {}

    with pytest.raises(SystemExit, match="at least two completed profiles"):
        _run(monkeypatch, _package(build_anything=build_anything), profiles=[FakeProfile("solo", 1)])


def test_single_profile_builders_sample_the_largest_libraries(monkeypatch) -> None:
    """Sampling by name would have missed this class of defect entirely.

    The first real finding was a builder that ran in about a second on two
    profiles and took seven on the biggest one. A sample that ignores size
    reports a pass on exactly the libraries where nothing goes wrong.
    """

    seen = []

    def build_per_person(db, profile):
        seen.append(profile.username)
        return {}

    monkeypatch.setattr(sweep_module, "SINGLE_PROFILE_SAMPLE", 2)
    people = [
        FakeProfile("small", 1, library_size=90),
        FakeProfile("biggest", 2, library_size=4200),
        FakeProfile("middling", 3, library_size=700),
    ]
    result, _ = _run(monkeypatch, _package(build_per_person=build_per_person), profiles=people)

    assert result.ok
    assert seen == ["biggest", "middling"]
    # And the row count travels with the result, so a latency can be read.
    assert {r.subject: r.scale for r in result.results} == {"biggest": 4200, "middling": 700}


def test_an_unstamped_profile_sorts_last_rather_than_crashing(monkeypatch) -> None:
    """A caller that did not measure library sizes still gets a sweep."""

    def build_per_person(db, profile):
        return {}

    monkeypatch.setattr(sweep_module, "SINGLE_PROFILE_SAMPLE", 3)
    people = [FakeProfile("unmeasured", 1), FakeProfile("measured", 2, library_size=10)]
    result, _ = _run(monkeypatch, _package(build_per_person=build_per_person), profiles=people)

    assert result.ok
    assert [r.subject for r in result.results] == ["measured", "unmeasured"]


def test_the_real_service_package_has_no_undeclared_database_functions() -> None:
    """The exclusion list is checked against the actual codebase here, so the
    sweep cannot first discover a gap on production."""

    _prepare_service_imports()
    import services  # noqa: PLC0415

    discovered = sweep_module.discover_session_functions(services)
    undeclared = [
        name
        for name in discovered
        if name not in sweep_module.EXCLUDED and not name.split(".", 1)[1].startswith("build_")
    ]
    stale = sorted(set(sweep_module.EXCLUDED) - set(discovered))

    assert undeclared == [], f"these reach the database and are unclassified: {undeclared}"
    assert stale == [], f"these exclusions name functions that no longer exist: {stale}"


def test_postgres_is_asked_for_a_read_only_transaction_and_sqlite_is_not() -> None:
    """The guard that stops a stray write from landing on production.

    Asserted in both directions: a missing statement on Postgres is a silent
    loss of the protection, and issuing it on SQLite is an error.
    """

    class Recorder:
        def __init__(self, dialect_name: str):
            self.bind = types.SimpleNamespace(dialect=types.SimpleNamespace(name=dialect_name))
            self.statements = []

        def execute(self, statement):
            self.statements.append(str(statement))

    postgres = Recorder("postgresql")
    sweep_module.make_read_only(postgres)
    assert postgres.statements == ["SET TRANSACTION READ ONLY"]

    sqlite = Recorder("sqlite")
    sweep_module.make_read_only(sqlite)
    assert sqlite.statements == []


# The environment-file reader moved to backend/env_file.py so the panel sweep
# and the credits backfill share one implementation; its tests moved with it,
# to backend/tests/test_env_file.py.


def test_every_swept_builder_has_a_call_plan() -> None:
    """A builder whose signature the planner does not recognise would be
    counted as covered while never being called."""

    _prepare_service_imports()
    import services  # noqa: PLC0415

    discovered = sweep_module.discover_session_functions(services)
    people = [FakeProfile("alpha", 1), FakeProfile("beta", 2)]
    unplanned = [
        name
        for name, function in discovered.items()
        if name not in sweep_module.EXCLUDED
        and name.split(".", 1)[1].startswith("build_")
        and not sweep_module.plan_call(name, function, people)
    ]

    assert unplanned == [], f"no call plan for: {unplanned}"
