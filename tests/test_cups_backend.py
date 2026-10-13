"""The CUPS path needs its own tests: `lp -n` repeats the whole payload.

Delegating copies to `lp -n` would replay the restore between copies, so the
epilogue forces the copy loop back into our own hands.
"""
import subprocess
import types

import pytest

import printer_linux

LABEL = "^XA^FDlabel^FS^XZ"
RESTORE = "^XA^LH0,0^MD0^CI0^JUR^XZ"


@pytest.fixture
def lp_calls(monkeypatch):
    """Capture the argv and stdin of every `lp` invocation."""
    calls = []

    def fake_run(cmd, input=None, capture_output=False, timeout=None):
        calls.append({"cmd": cmd, "input": input.decode("utf-8") if input else ""})
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(printer_linux.subprocess, "run", fake_run)
    monkeypatch.setattr(printer_linux, "HAS_CUPS", True)
    return calls


@pytest.fixture
def cups(lp_calls):
    return printer_linux.CUPSPrinter(printer_name="zebra", timeout=5)


def test_copies_are_expanded_locally_when_a_restore_follows(cups, lp_calls):
    cups.print_zpl(LABEL, copies=3, epilogue=RESTORE)
    call = lp_calls[0]
    assert "-n" not in call["cmd"], "lp -n would replay the restore between copies"
    assert call["input"] == LABEL * 3 + RESTORE


def test_lp_still_handles_copies_when_there_is_no_restore(cups, lp_calls):
    # Keeps the spooler doing the work in "off" mode, as it always has.
    cups.print_zpl(LABEL, copies=3, epilogue=None)
    call = lp_calls[0]
    assert "-n" in call["cmd"] and call["cmd"][call["cmd"].index("-n") + 1] == "3"
    assert call["input"] == LABEL


def test_restore_lands_once_at_the_end_of_a_batch(cups, lp_calls):
    cups.print_batch_zpl([LABEL, LABEL], copies_each=2, epilogue=RESTORE)
    sent = lp_calls[0]["input"]
    assert sent == LABEL * 4 + RESTORE
    assert sent.count(RESTORE) == 1


def test_jobs_still_go_out_raw(cups, lp_calls):
    cups.print_zpl(LABEL, copies=1, epilogue=RESTORE)
    assert "raw" in lp_calls[0]["cmd"]
