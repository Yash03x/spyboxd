import importlib.util
from pathlib import Path
import plistlib

import pytest

spec = importlib.util.spec_from_file_location("local_services", Path(__file__).resolve().parents[2] / "scripts/local_services.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_services_are_loopback_only_durable_and_have_no_credentials():
    definitions = launcher.service_definitions(Path("/space in/repo"), Path("/private/node"), Path("/private/logs"))
    assert set(definitions) == {"api", "web", "rss"}
    for name, definition in definitions.items():
        assert definition["KeepAlive"] is True
        assert definition["RunAtLoad"] is True
        assert definition["ThrottleInterval"] >= 10
        assert definition["Umask"] == 0o077
        assert not any("TOKEN" in key or "SECRET" in key for key in definition["EnvironmentVariables"])
        assert plistlib.loads(plistlib.dumps(definition)) == definition
        if name != "rss":
            assert ("localhost" if name == "web" else "127.0.0.1") in definition["ProgramArguments"]
        assert "sh" not in definition["ProgramArguments"]
    assert definitions["rss"]["ProgramArguments"][-1] == "rss_worker"


def test_different_installation_and_symlink_are_not_overwritten(tmp_path):
    path = tmp_path / "agent.plist"
    expected = {"Label": "spyboxd", "WorkingDirectory": "/correct"}
    launcher.validate_existing(path, expected)
    path.write_bytes(plistlib.dumps(expected))
    launcher.validate_existing(path, expected)
    path.write_bytes(plistlib.dumps({**expected, "WorkingDirectory": "/other"}))
    with pytest.raises(ValueError, match="different installation"):
        launcher.validate_existing(path, expected)
    link = tmp_path / "link.plist"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="symlinked"):
        launcher.validate_existing(link, expected)


def test_bootstrap_retries_launchd_teardown_race_but_is_bounded(monkeypatch, tmp_path):
    from types import SimpleNamespace
    attempts = []
    def launch(*args, **kwargs):
        attempts.append(args)
        return SimpleNamespace(returncode=5 if len(attempts) < 3 else 0)
    monkeypatch.setattr(launcher, 'launchctl', launch)
    monkeypatch.setattr(launcher.time, 'sleep', lambda _: None)
    launcher.bootstrap('gui/123', tmp_path / 'service.plist')
    assert len(attempts) == 3
    monkeypatch.setattr(launcher, 'launchctl', lambda *a, **k: SimpleNamespace(returncode=5))
    with pytest.raises(RuntimeError, match='could not load'):
        launcher.bootstrap('gui/123', tmp_path / 'service.plist')
