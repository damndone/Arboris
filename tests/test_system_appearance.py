from __future__ import annotations

from subprocess import CompletedProcess

from workbench.services.system_appearance import detect_system_appearance


def test_detects_dark_macos_appearance_with_a_fixed_defaults_command() -> None:
    calls: list[tuple[object, ...]] = []

    def run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        calls.append((*args, kwargs))
        return CompletedProcess(args[0], 0, stdout="Dark\n", stderr="")

    result = detect_system_appearance(system_name="Darwin", run=run)

    assert result == {"theme": "dark", "source": "darwin-native"}
    assert calls[0][0] == [
        "/usr/bin/defaults",
        "read",
        "NSGlobalDomain",
        "AppleInterfaceStyle",
    ]
    assert calls[0][1]["shell"] is False


def test_missing_macos_dark_key_means_light_appearance() -> None:
    def run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="The domain/default pair does not exist",
        )

    assert detect_system_appearance(system_name="Darwin", run=run) == {
        "theme": "light",
        "source": "darwin-native",
    }


def test_unknown_platform_falls_back_to_browser_without_running_a_command() -> None:
    def run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        raise AssertionError("non-Darwin platforms must not run macOS defaults")

    assert detect_system_appearance(system_name="Linux", run=run) == {
        "theme": None,
        "source": "browser",
    }


def test_unexpected_defaults_failure_falls_back_to_browser() -> None:
    def run(*args: object, **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(args[0], 2, stdout="", stderr="permission denied")

    assert detect_system_appearance(system_name="Darwin", run=run) == {
        "theme": None,
        "source": "browser",
    }
