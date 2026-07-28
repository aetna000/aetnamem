from __future__ import annotations

from aetnamem.trial import hermes_standalone as plugin


class _Context:
    def __init__(self) -> None:
        self.hooks: dict[str, object] = {}

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks[name] = callback


def test_hermes_general_plugin_observes_then_injects_only_after_canary(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    inject = False

    context = _Context()
    plugin.register(context)
    assert set(context.hooks) == {
        "pre_llm_call",
        "post_llm_call",
        "on_session_finalize",
    }

    def fake_call(name: str, arguments: dict[str, object]):
        calls.append((name, arguments))
        if name == "trial_prepare":
            return {
                "inject": inject,
                "context": "approved zsh context" if inject else "",
                "exposure_id": "tx_1" if inject else None,
            }
        if name == "trial_exposure_shown":
            return {"confirmed": True}
        if name == "trial_capture":
            return {"captured": 1}
        raise AssertionError(name)

    monkeypatch.setattr(plugin, "_call", fake_call)

    assert plugin.before_llm("s1", "Remember my shell is zsh.") is None
    plugin.after_llm("s1", "Remember my shell is zsh.")
    assert calls[-1][0] == "trial_capture"

    inject = True
    injected = plugin.before_llm("s2", "Which shell do I prefer?")
    assert injected is not None
    assert "zsh" in injected["context"]
    plugin.after_llm("s2", "Which shell do I prefer?")
    assert [name for name, _ in calls[-2:]] == [
        "trial_exposure_shown",
        "trial_capture",
    ]
