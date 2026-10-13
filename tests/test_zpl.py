"""Unit tests for the outbound ZPL transforms."""
import pytest

import config
from zpl import (
    apply_zpl_darkness,
    apply_zpl_offsets,
    build_restore_epilogue,
    clamp_darkness,
    prepare_zpl,
    restore_mode,
    strip_persistent,
)

# What the Main-API renderer actually emits (mulelab/printing/client.py).
RENDERED = "^XA^PW620^LL240^LH140,30^FO20,50^A0N,28,28^FDLOT A^FS^XZ"


def cfg(**overrides):
    settings = dict(config.DEFAULT_CONFIG)
    settings.update(overrides)
    return settings


def calibrated(**overrides):
    return cfg(label_origin_x=210, label_origin_y=24, label_width=480, **overrides)


class TestPrintWidth:
    """^PW used to be forced to a hardcoded 832 — a 4"/203dpi literal."""

    def test_widens_to_cover_the_calibrated_offset(self):
        # Shifting right by 210 pushes a 480-dot label to 690 absolute dots,
        # past the renderer's ^PW620, so the width has to grow to match.
        assert "^PW690" in apply_zpl_offsets(RENDERED, calibrated())

    def test_never_narrows_a_width_that_already_covers_the_label(self):
        wide = "^XA^PW900^LL240^FO20,50^FDx^FS^XZ"
        assert "^PW900" in apply_zpl_offsets(wide, calibrated())
        assert "^PW690" not in apply_zpl_offsets(wide, calibrated())

    def test_injects_a_width_when_the_payload_has_none(self):
        assert "^PW690" in apply_zpl_offsets("^XA^FO20,50^FDx^FS^XZ", calibrated())

    def test_emits_nothing_when_the_label_has_not_been_measured(self):
        # Calibrated origin but no measured width: we do not know how wide the
        # label is, so guessing a width is worse than leaving the printer's.
        out = apply_zpl_offsets(RENDERED, cfg(label_origin_x=210, label_origin_y=24))
        assert "^PW620" in out

    def test_the_hardcoded_832_is_gone(self):
        assert "832" not in apply_zpl_offsets(RENDERED, calibrated())


class TestRestoreEpilogue:
    def test_defaults_to_recalling_the_printers_saved_config(self):
        assert build_restore_epilogue(cfg()) == "^XA^LH0,0^MD0^CI0^JUR^XZ"

    def test_off_emits_nothing(self):
        assert build_restore_epilogue(cfg(printer_restore_mode="off")) == ""

    def test_neutralize_puts_back_the_power_on_values(self):
        assert build_restore_epilogue(
            calibrated(printer_restore_mode="neutralize", label_darkness=12)
        ) == "^XA^LH0,0^MD0^CI0^XZ"

    def test_neutralize_runs_even_when_the_service_is_uncalibrated(self):
        # The renderer's own ^LH140,30 and ^CI28 are left behind otherwise —
        # exactly what shifted the offline LIMS's labels.
        assert build_restore_epilogue(
            cfg(printer_restore_mode="neutralize")
        ) == "^XA^LH0,0^MD0^CI0^XZ"

    def test_an_unknown_mode_falls_back_to_the_default(self):
        # A hand-edited config.json must not be able to silently disable the
        # restore — that is the failure the whole change exists to prevent.
        assert build_restore_epilogue(cfg(printer_restore_mode="wat")) == "^XA^LH0,0^MD0^CI0^JUR^XZ"
        assert restore_mode(cfg(printer_restore_mode=None)) == "jur"

    def test_the_epilogue_prints_no_label(self):
        # A format carrying only configuration and no ^FD field data does not
        # feed media, which is what makes a per-job restore affordable.
        assert "^FD" not in build_restore_epilogue(cfg())


class TestDarkness:
    def test_zero_leaves_the_payload_byte_identical(self):
        assert apply_zpl_darkness(RENDERED, cfg(label_darkness=0)) == RENDERED

    def test_replaces_rather_than_compounds_an_existing_md(self):
        out = apply_zpl_darkness("^XA^MD5^FDx^FS^XZ", cfg(label_darkness=12))
        assert "^MD12" in out and "^MD5" not in out

    @pytest.mark.parametrize("value,expected", [
        (99, 30), (-99, -30), ("8", 8), (None, 0), ("nonsense", 0),
    ])
    def test_clamps_to_the_documented_range(self, value, expected):
        assert clamp_darkness(value) == expected


class TestUnconfiguredServiceIsANoOp:
    def test_default_config_does_not_touch_the_payload(self):
        # The safety property behind shipping this on by default: with nothing
        # configured, the bytes going to the printer are exactly what came in.
        assert prepare_zpl(RENDERED, cfg()) == RENDERED


class TestStripPersistent:
    """Nothing that outlives the job may leave the service."""

    @pytest.mark.parametrize("command", [
        "^JUS", "^JUF", "^JUN", "^JUA", "~JC", "~JL", "~JR", "~SD15", "^SD8", "~SD20.5",
    ])
    def test_removes_each_persistent_command(self, command):
        zpl = f"^XA{command}^FO10,10^FDx^FS^XZ"
        assert strip_persistent(zpl) == "^XA^FO10,10^FDx^FS^XZ"

    def test_leaves_jur_and_modal_commands_alone(self):
        # ^JUR only copies saved config into the active one; the modal
        # commands are handed back by the epilogue, not stripped.
        zpl = "^XA^JUR^XZ" + RENDERED + "^XA^MD5^XZ"
        assert strip_persistent(zpl) == zpl

    def test_no_restore_mode_emits_anything_persistent(self):
        for mode in ("jur", "neutralize", "off"):
            out = build_restore_epilogue(calibrated(printer_restore_mode=mode, label_darkness=5))
            assert strip_persistent(out) == out, mode
