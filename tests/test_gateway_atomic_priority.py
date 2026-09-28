from __future__ import annotations

from pathlib import Path

from middle_man.gateway import ContextBuilder, GatewayConfig


def test_exact_method_stays_atomic_without_dragging_whole_class(tmp_path: Path) -> None:
    siblings = "".join(f"    def sibling_{number}(self):\n        return {number}\n" for number in range(100))
    source = "class LargeClass:\n" + siblings + "    def target(self, value):\n        checked = value + 1\n        return checked\n"
    (tmp_path / "service.py").write_text(source, encoding="utf-8")
    pack = ContextBuilder(GatewayConfig(tmp_path)).build("LargeClass.target", max_context_tokens=10)
    combined = "\n".join(item.text for item in pack.excerpts if item.path == "service.py")
    assert "def target" in combined and "return checked" in combined
    assert "class LargeClass" in combined
    assert "def sibling_50" not in combined
    assert pack.metrics.source_lines_selected < 20
    assert any(warning.startswith("BUDGET_EXCEEDED_FOR_REQUIRED_SYMBOL") for warning in pack.warnings)
