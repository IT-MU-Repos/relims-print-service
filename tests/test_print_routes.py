"""End-to-end byte capture: what actually reaches the printer.

The invariant these defend: a job must not leave a modal ZPL command sitting in
the printer's active configuration, because the label printer is shared with the
legacy VB.NET LIMS app and with driver printing.
"""
import re
import sys

import pytest

RENDERED = "^XA^PW620^LL240^LH140,30^FO20,50^A0N,28,28^FDLOT A^FS^XZ"
RESTORE = "^XA^LH0,0^MD0^CI0^JUR^XZ"

# Commands that update the printer's active configuration and stay in effect
# for every later format until changed again or the printer is powered off.
MODAL = re.compile(r'\^(MD-?\d+|LH\d+,\d+|PW\d+|LL\d+|CI\d+)', re.IGNORECASE)


def print_one(client, **body):
    payload = {"zpl": RENDERED}
    payload.update(body)
    return client.post("/print", json=payload)


class TestRestoreIsSent:
    def test_every_job_hands_the_printer_back(self, client, configure, fake_printer):
        assert print_one(client).status_code == 200
        assert fake_printer.received.endswith(RESTORE)

    def test_restore_is_the_last_thing_after_a_modal_command(self, client, configure, fake_printer):
        configure(label_origin_x=210, label_origin_y=24, label_width=480, label_darkness=12)
        print_one(client)
        sent = fake_printer.received
        # The invariant, stated directly: nothing modal may be left dangling.
        assert MODAL.search(sent), "test is meaningless if the job wrote nothing modal"
        assert sent.endswith(RESTORE)

    def test_raw_jobs_are_restored_too(self, client, configure, fake_printer):
        # `raw` means "do not rewrite my ZPL", not "do not clean up". The
        # calibration ruler is raw and still writes ^PW and ^LL.
        configure(label_darkness=12)
        print_one(client, zpl="^XA^PW832^LL300^LH0,0^FO10,10^FDruler^FS^XZ", raw=True)
        sent = fake_printer.received
        assert "^MD12" not in sent, "raw payload must not be transformed"
        assert sent.endswith(RESTORE)

    def test_off_reproduces_the_old_bytes_exactly(self, client, configure, fake_printer):
        configure(printer_restore_mode="off")
        print_one(client)
        assert fake_printer.received == RENDERED

    def test_neutralize_puts_back_the_power_on_values(self, client, configure, fake_printer):
        configure(label_darkness=12, printer_restore_mode="neutralize")
        print_one(client)
        assert fake_printer.received.endswith("^XA^LH0,0^MD0^CI0^XZ")


class TestRestoreLandsExactlyOnce:
    def test_after_the_last_copy_not_between_copies(self, client, configure, fake_printer):
        # A restore between copies would print copies 2..n at the handed-back
        # settings — the label would come out at the wrong darkness.
        configure(label_darkness=12)
        print_one(client, copies=3)
        sent = fake_printer.received
        assert sent.count(RESTORE) == 1
        assert sent.count("^FDLOT A^FS") == 3
        assert sent.endswith(RESTORE)

    def test_after_the_last_label_of_a_batch(self, client, configure, fake_printer):
        configure(label_darkness=12)
        res = client.post("/print-batch", json={"zpls": [RENDERED, RENDERED, RENDERED]})
        assert res.status_code == 200
        sent = fake_printer.received
        assert sent.count(RESTORE) == 1
        assert sent.endswith(RESTORE)

    def test_label_and_restore_share_one_connection(self, client, configure, fake_printer):
        # Two connections would let another application's job interleave
        # between the label and the restore.
        print_one(client, copies=2)
        fake_printer.wait()
        assert len(fake_printer.connections) == 1


class TestOriginAllowlist:
    def test_a_disallowed_origin_cannot_print(self, client, configure, fake_printer):
        res = client.post("/print", json={"zpl": RENDERED},
                          headers={"Origin": "https://evil.example"})
        assert res.status_code == 403
        assert fake_printer.settle() == "", "the side effect must not happen"

    def test_a_disallowed_origin_cannot_change_settings(self, client, configure):
        res = client.post("/config", json={"label_darkness": 30},
                          headers={"Origin": "https://evil.example"})
        assert res.status_code == 403

    def test_an_allowed_origin_still_works(self, client, configure, fake_printer):
        res = client.post("/print", json={"zpl": RENDERED},
                          headers={"Origin": "http://localhost:5577"})
        assert res.status_code == 200

    def test_a_request_with_no_origin_still_works(self, client, configure, fake_printer):
        # curl, the installer smoke test and the manager tray send no Origin.
        assert print_one(client).status_code == 200


class TestConfigValidation:
    def test_an_invalid_restore_mode_is_rejected_not_stored(self, client, configure):
        res = client.post("/config", json={"printer_restore_mode": "nonsense"})
        assert res.status_code == 200
        assert res.get_json()["printer_restore_mode"] == "jur"

    def test_the_allowlist_cannot_be_rewritten_over_http(self, client, configure):
        client.post("/config", json={"allowed_origins": ["https://evil.example"]})
        res = client.post("/print", json={"zpl": RENDERED},
                          headers={"Origin": "https://evil.example"})
        assert res.status_code == 403


class TestRealFrontendOriginsKeepWorking:
    """The allowlist must not stop the apps that actually print.

    A browser sends the SPA's own origin on a fetch to localhost:5577, so an
    origin missing from the default list means printing silently 403s in
    production — the regression this hardening could most easily cause.
    """

    @pytest.mark.parametrize("origin", [
        "https://labserve.net",
        "https://www.labserve.net",
        "https://www.it-mu.co.za",
        "https://eacl.it-mu.co.za",
        "https://staging.labserve.net",
        "https://staging.it-mu.co.za",
        "https://test.labserve.net",
        "http://localhost:5013",   # mule dev
        "http://localhost:5003",   # client-portal dev
        "http://127.0.0.1:5013",
    ])
    def test_a_real_app_origin_can_print(self, client, configure, fake_printer, origin):
        res = client.post("/print", json={"zpl": RENDERED}, headers={"Origin": origin})
        assert res.status_code == 200, f"{origin} would be unable to print"


class TestResetPrinterFlagIsGone:
    def test_print_no_longer_honours_reset_printer(self, client, configure, fake_printer):
        # The flag is what silently factory-recalled printers via the
        # calibration button in v2.0.13-v2.0.15.
        print_one(client, reset_printer=True)
        sent = fake_printer.received
        assert "^JUF" not in sent and "~JC" not in sent


PERSISTENT = re.compile(r'\^JU[SFNA]|~J[CLR]|[~^]SD', re.IGNORECASE)


class TestNeverChangesThePrinter:
    """The service applies its settings per job and never writes the printer's own."""

    @pytest.mark.parametrize("path", ["/reset-printer", "/printer-baseline"])
    def test_the_reset_and_baseline_routes_are_gone(self, client, configure, fake_printer, path):
        assert client.post(path, json={}).status_code in (404, 405)
        assert fake_printer.settle() == ""

    @pytest.mark.parametrize("mode", ["jur", "neutralize", "off"])
    def test_persistent_commands_in_a_payload_never_reach_the_printer(
        self, client, configure, fake_printer, mode
    ):
        configure(printer_restore_mode=mode, label_origin_x=210, label_darkness=12)
        poisoned = "^XA^JUS~JC^SD15^FO10,10^FDx^FS^JUF^XZ"
        print_one(client, zpl=poisoned)
        print_one(client, zpl=poisoned, raw=True)
        fake_printer.wait(2)
        assert not PERSISTENT.search(fake_printer.received)

    def test_nor_through_a_batch(self, client, configure, fake_printer):
        configure()
        client.post("/print-batch", json={"zpls": ["^XA^JUS^FDa^FS^XZ", "^XA~JC^FDb^FS^XZ"]})
        assert not PERSISTENT.search(fake_printer.received)


class StubPrinter:
    """Records every job; the first `fail_first` calls report failure."""

    def __init__(self, fail_first=1):
        self.jobs = []
        self.fail_first = fail_first

    def print_zpl(self, zpl, copies=1, epilogue=None):
        self.jobs.append(zpl * copies + (epilogue or ""))
        if len(self.jobs) <= self.fail_first:
            return {"success": False, "error": "simulated"}
        return {"success": True, "copies": copies}

    def print_batch_zpl(self, zpls, copies_each=1, epilogue=None):
        result = self.print_zpl("".join(z * copies_each for z in zpls), epilogue=epilogue)
        return dict(result, printed=0 if not result["success"] else len(zpls), total=len(zpls))


def _use_stub(monkeypatch, client, stub):
    module = sys.modules[client.application.import_name]
    monkeypatch.setattr(module, "get_printer", lambda cfg=None: stub)
    return module


class TestFailsafes:
    def test_a_failed_job_still_hands_the_printer_back(self, client, configure, monkeypatch):
        stub = StubPrinter()
        _use_stub(monkeypatch, client, stub)
        assert print_one(client).status_code == 500
        # The failed job, then exactly one restore on its own.
        assert stub.jobs[1:] == [RESTORE]

    def test_a_failed_batch_still_hands_the_printer_back(self, client, configure, monkeypatch):
        stub = StubPrinter()
        _use_stub(monkeypatch, client, stub)
        res = client.post("/print-batch", json={"zpls": [RENDERED, RENDERED]})
        assert res.status_code == 500
        assert stub.jobs[1:] == [RESTORE]

    def test_a_successful_job_sends_no_extra_restore(self, client, configure, monkeypatch):
        stub = StubPrinter(fail_first=0)
        _use_stub(monkeypatch, client, stub)
        print_one(client)
        assert len(stub.jobs) == 1 and stub.jobs[0].endswith(RESTORE)

    def test_startup_hands_the_printer_back(self, client, configure, fake_printer):
        module = sys.modules[client.application.import_name]
        module.send_startup_restore()
        assert fake_printer.received == RESTORE

    def test_startup_sends_nothing_when_restore_is_off(self, client, configure, fake_printer):
        configure(printer_restore_mode="off")
        sys.modules[client.application.import_name].send_startup_restore()
        assert fake_printer.settle() == ""

    def test_startup_sends_nothing_without_a_printer(self, client, fake_printer):
        # No `configure`: the packaged defaults name no printer.
        assert sys.modules[client.application.import_name].send_startup_restore() is None
        assert fake_printer.settle() == ""

    @pytest.mark.parametrize("change", ["^CC#", "~CC#", "^CT#", "~CT#", "^cc#"])
    def test_a_changed_command_prefix_cannot_smuggle_a_save(self, client, configure, fake_printer, change):
        # With the prefix change stripped the printer still reads `^`/`~`, so
        # `#JUS` stays inert text instead of becoming a save.
        print_one(client, zpl=f"^XA{change}^FO10,10^FDx^FS#JUS#XZ^XZ", raw=True)
        sent = fake_printer.received
        assert not re.search(r"[~^]C[CT]", sent, re.IGNORECASE)
        assert not PERSISTENT.search(sent)

    @pytest.mark.parametrize("path,body", [
        ("/print", {"zpl": "~!!\n~A\nPRINT DARKNESS\t:\t30\nEND\n"}),
        ("/print-batch", {"zpls": [RENDERED, "~!!\nEND\n"]}),
    ])
    def test_a_printer_configuration_block_is_refused(self, client, configure, fake_printer, path, body):
        res = client.post(path, json=body)
        assert res.status_code == 400
        assert fake_printer.settle() == "", "nothing may reach the printer"

    def test_health_reports_the_restore_mode(self, client, configure):
        configure(printer_restore_mode="neutralize")
        assert client.get("/health").get_json()["restore_mode"] == "neutralize"
