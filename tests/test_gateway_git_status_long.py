from __future__ import annotations

from middle_man.gateway.compact import OutputCompactor


def test_human_git_status_categories_without_boilerplate() -> None:
    status = ("On branch main\n"
              "Changes to be committed:\n"
              "  (use \"git restore --staged\" to unstage)\n"
              "        new file:   app/new.py\n"
              "        renamed:    app/old.py -> app/current.py\n"
              "Changes not staged for commit:\n"
              "        modified:   app/auth.py\n"
              "        deleted:    app/deleted.py\n"
              "Untracked files:\n"
              "        tests/test_auth.py\n")
    output = OutputCompactor().compact("git-status", status).compacted_text
    for path in ("app/new.py", "app/old.py", "app/current.py", "app/auth.py", "app/deleted.py", "tests/test_auth.py"):
        assert path in output
    assert "On branch main" not in output
    assert "Added (1)" in output and "Modified (1)" in output and "Untracked (1)" in output
