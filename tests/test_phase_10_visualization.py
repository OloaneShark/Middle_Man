import sys

import pytest

from middle_man.lab.suites import build_suite
from middle_man.lab.visualization import VisualizationUnavailable, render_suite_plots


def test_visualization_is_optional(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    result = build_suite("mixed").run()
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    with pytest.raises(VisualizationUnavailable, match="optional"):
        render_suite_plots(result, tmp_path)


def test_headless_plots_use_simulated_results_and_safe_filenames(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    result = build_suite("scheduler-comparison").run()
    paths = render_suite_plots(result, tmp_path)

    assert len(paths) == 4
    assert all(path.parent == tmp_path for path in paths)
    assert all(path.name.startswith(("scheduler-mixed-", "scheduler-comparison-")) for path in paths)
    assert all(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for path in paths)
