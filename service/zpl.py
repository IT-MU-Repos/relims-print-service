"""Outbound ZPL transforms, shared by the Windows and Linux services.

Lives in its own module because `app.py` and `app_linux.py` carried
copy-pasted versions of all of this and have drifted before (`raw` was
honoured only on Linux until v2.0.13). One copy cannot drift.

The guiding rule for everything here: **the service applies its settings to
every job, and never changes the printer's settings.** A label printer is
usually shared — the offline VB.NET LIMS prints on the same unit — and that app
sends no ^LH, ^PW, ^LL or ^CI of its own. It relies on the printer's own setup
(for the Citizen CL-E321 that is `CitizenPrinter.CONFIG_STR` in LIMS_SOURCE,
which its Printer Maintenance -> Fix My Printer re-sends). So:

  * our settings (calibrated origin, darkness) ride inside each label;
  * every modal command a job leaves behind is handed back afterwards by
    `build_restore_epilogue`;
  * nothing that writes to non-volatile memory, recalls defaults or
    re-calibrates media ever leaves the service — see `strip_persistent`.

Before 2.1.0 the service had a "Reset Printer Settings" action (^JUF + ~JC)
and briefly a ^JUS "baseline". Both rewrote the printer under the offline LIMS
and are gone.
"""
import re

# Commands that change the printer beyond the current job's active state:
# ^JUS saves to non-volatile memory, ^JUF/^JUN/^JUA recall defaults, ~JC/~JL
# re-learn the media (and commit the result on most firmware), ~JR resets the
# printer, ~SD/^SD set the base darkness. Stripped from every outgoing payload,
# raw included — a label imported from elsewhere could carry any of them.
#
# ^CC/~CC/^CT/~CT go too, with their one-character argument: they change the
# command prefix itself, so a payload could switch to `#` and send `#JUS` past
# a filter that only knows `^` and `~`. The new prefix is also modal, and would
# turn every later LIMS label into plain text.
_PERSISTENT_RE = re.compile(
    r'[~^]C[CT].|\^JU[SFNA]|~J[CLR]|[~^]SD\d{0,2}(?:\.\d)?', re.IGNORECASE | re.DOTALL
)

# The Citizen's native configuration mode — how LIMS Source's
# CitizenPrinter.CONFIG_STR rewrites the printer's permanent setup. It is a
# block, not a command, so it cannot be stripped safely; a job carrying it is
# refused outright.
CITIZEN_CONFIG_MARKER = "~!!"

# Power-on values for what a label leaves behind: label home, darkness
# adjustment, code page. The offline LIMS sets none of these, so these are what
# it assumes.
_POWER_ON_VALUES = "^LH0,0^MD0^CI0"

# ^MD is a RELATIVE darkness adjustment layered on the printer's own setting
# (~SD / front panel), so 0 means "leave the printer alone". Zebra's documented
# range is -30..+30.
DARKNESS_MIN = -30
DARKNESS_MAX = 30

# How a job hands the printer back to whatever else uses it.
RESTORE_MODE_JUR = "jur"
RESTORE_MODE_NEUTRALIZE = "neutralize"
RESTORE_MODE_OFF = "off"
RESTORE_MODES = (RESTORE_MODE_JUR, RESTORE_MODE_NEUTRALIZE, RESTORE_MODE_OFF)
DEFAULT_RESTORE_MODE = RESTORE_MODE_JUR


def _int(cfg, key):
    try:
        return int(cfg.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def apply_zpl_offsets(zpl, cfg):
    """Adjust ZPL positioning using calibrated origin + fine-tune offsets.

    When calibration is active (label_origin_x/y > 0), REPLACES the ^LH
    in incoming ZPL with the calibrated label-edge position. This means
    Django's ^LH140,30 (a guess) gets replaced with the measured position,
    and all ^FO content positions are preserved relative to the label edge.

    When calibration is NOT active, falls back to additive fine-tune only.

    `cfg` is passed in rather than loaded here so one job resolves its settings
    once, and so a Test Print can render through values that are not saved.
    """
    origin_x = _int(cfg, "label_origin_x")
    origin_y = _int(cfg, "label_origin_y")
    fine_x = _int(cfg, "label_offset_x")
    fine_y = _int(cfg, "label_offset_y")
    calibrated = origin_x > 0 or origin_y > 0

    if calibrated:
        # REPLACE mode: set ^LH to the calibrated label edge + fine-tune.
        # This overrides whatever ^LH Django sent (e.g., ^LH140,30) with
        # the measured printhead-to-label offset.
        lh_x = max(0, origin_x + fine_x)
        lh_y = max(0, origin_y + fine_y)

        def replace_lh(match):
            return f"^LH{lh_x},{lh_y}"

        if re.search(r'\^LH\d+,\d+', zpl, re.IGNORECASE):
            zpl = re.sub(r'\^LH(\d+),(\d+)', replace_lh, zpl, flags=re.IGNORECASE)
        else:
            zpl = re.sub(r'(\^XA)', rf'\1^LH{lh_x},{lh_y}', zpl, flags=re.IGNORECASE)

        zpl = _widen_print_width(zpl, origin_x + _int(cfg, "label_width"))
    else:
        # ADDITIVE mode (no calibration): just add fine-tune to existing ^LH.
        if fine_x == 0 and fine_y == 0:
            return zpl

        def adjust_lh(match):
            x = int(match.group(1)) + fine_x
            y = int(match.group(2)) + fine_y
            return f"^LH{max(0, x)},{max(0, y)}"

        if re.search(r'\^LH\d+,\d+', zpl, re.IGNORECASE):
            zpl = re.sub(r'\^LH(\d+),(\d+)', adjust_lh, zpl, flags=re.IGNORECASE)
        else:
            lh = f"^LH{max(0, fine_x)},{max(0, fine_y)}"
            zpl = re.sub(r'(\^XA)', r'\1' + lh, zpl, flags=re.IGNORECASE)

    return zpl


def _widen_print_width(zpl, needed):
    """Ensure ^PW is wide enough to cover the calibrated offset, never narrower.

    ^FO coordinates are relative to ^LH but ^PW clips in ABSOLUTE printhead
    dots, so shifting a label right by the calibrated origin can push content
    past a ^PW that was correct before the shift.

    This used to force a hardcoded ^PW832 over whatever the payload carried —
    a 4"/203dpi literal that is wrong on a 2" or 300dpi head and threw away a
    correct width. Now it only ever widens: a payload whose ^PW already covers
    `needed` is left untouched, and with nothing measured (needed == 0) no ^PW
    is emitted at all.
    """
    if needed <= 0:
        return zpl

    existing = re.search(r'\^PW(\d+)', zpl, re.IGNORECASE)
    if existing is None:
        return re.sub(r'(\^XA)', rf'\1^PW{needed}', zpl, count=0, flags=re.IGNORECASE)
    if int(existing.group(1)) >= needed:
        return zpl
    return re.sub(r'\^PW\d+', f'^PW{needed}', zpl, flags=re.IGNORECASE)


def apply_zpl_darkness(zpl, cfg):
    """Inject ^MD<n> so labels print lighter (negative) or darker (positive).

    ^MD is relative to the printer's own darkness (~SD / front panel), so a
    configured 0 emits nothing at all and leaves the outgoing ZPL byte-identical
    to what an unconfigured service would send.

    Darkness is label-global — it affects barcodes and graphics along with text.
    ZPL has no text-only darkness; the Django renderer's `bold` double-strike is
    the closest equivalent for text alone.
    """
    darkness = clamp_darkness(cfg.get("label_darkness", 0))
    if darkness == 0:
        return zpl
    # Strip any ^MD already present — Zebra treats multiple ^MD commands within
    # one format as CUMULATIVE, so layering ours on top would compound.
    zpl = re.sub(r'\^MD-?\d+', '', zpl, flags=re.IGNORECASE)
    # Unbounded: one ^MD per format, so a multi-format payload is covered too.
    return re.sub(r'(\^XA)', rf'\1^MD{darkness}', zpl, flags=re.IGNORECASE)


def clamp_darkness(value):
    """Read a darkness setting, clamped to the documented range. 0 on garbage.

    Clamps rather than rejects, so a hand-edited config.json can never produce
    out-of-range ZPL.
    """
    try:
        darkness = int(value)
    except (TypeError, ValueError):
        return 0
    return max(DARKNESS_MIN, min(DARKNESS_MAX, darkness))


def restore_mode(cfg):
    """The configured restore mode, falling back to the default on anything odd."""
    mode = cfg.get("printer_restore_mode", DEFAULT_RESTORE_MODE)
    if isinstance(mode, str) and mode.lower() in RESTORE_MODES:
        return mode.lower()
    return DEFAULT_RESTORE_MODE


def build_restore_epilogue(cfg):
    """The config-only format that hands the printer back after a job.

    Appended once per job, after the last copy, inside the same connection or
    spooler document — see `printer.py`. Without it a ReLIMS label leaves its
    ^MD darkness, ^LH label home, ^PW width, and the renderer's own ^LL and
    ^CI, sitting in the printer's active configuration for whatever prints
    next — which is exactly how the offline LIMS's labels went wrong.

    A format carrying only configuration commands and no field data does not
    print a label, so this costs media nothing. Neither mode writes anything to
    the printer's non-volatile memory.

    Modes:
      "jur"        — the power-on values, then ^JUR, which copies the printer's
                     saved configuration back over the active one. ^JUR
                     restores wholesale, so it also undoes the ^PW and ^LL the
                     Main-API renderer emits, and overrides the values before
                     it. The values are there as a failsafe: a printer whose
                     emulation ignores ^JUR still gets position, darkness and
                     code page back. The default.
      "neutralize" — for a printer whose ZPL emulation ignores ^JU: put back
                     the power-on values the offline LIMS assumes (label home
                     0,0, no darkness adjustment, code page 0). Cannot restore
                     ^PW / ^LL, whose power-on values depend on the printer.
      "off"        — emit nothing; pre-2.1.0 behaviour.
    """
    mode = restore_mode(cfg)
    if mode == RESTORE_MODE_OFF:
        return ""
    # Unconditional, not only when our own settings are non-zero: the renderer
    # sends ^LH140,30 and ^CI28 even on an uncalibrated service.
    if mode == RESTORE_MODE_JUR:
        return f"^XA{_POWER_ON_VALUES}^JUR^XZ"
    return f"^XA{_POWER_ON_VALUES}^XZ"


def strip_persistent(zpl):
    """Remove every command that would change the printer beyond this job."""
    return _PERSISTENT_RE.sub("", zpl)


def carries_printer_config(zpl):
    """True if a payload would put the printer into its own configuration mode."""
    return CITIZEN_CONFIG_MARKER in (zpl or "")


def hand_back(printer, cfg, logger, reason):
    """Send the restore as a job of its own. Best effort; never raises.

    The normal restore rides inside the label's own job. This is the failsafe
    for when that cannot be trusted to have arrived: a job that failed partway
    (the label may be on the printer, the restore not), and service startup
    (a crash between label and restore, or leftovers from a pre-2.1.0 service).
    Prints no label — a configuration-only format feeds no media.
    """
    epilogue = build_restore_epilogue(cfg)
    if not epilogue:
        return None
    try:
        result = printer.print_zpl(epilogue, copies=1)
    except Exception as e:  # a failsafe must not turn one failure into two
        result = {"success": False, "error": str(e)}
    if result.get("success"):
        logger.info("Printer handed back (%s): %s", reason, epilogue)
    else:
        logger.warning("Could not hand the printer back (%s): %s", reason, result.get("error"))
    return result


def prepare_zpl(zpl, cfg):
    """Apply every outbound ZPL transform: position first, then darkness.

    Darkness is deliberately NOT folded into apply_zpl_offsets — that function
    returns early when no fine-tune is set, which would skip darkness entirely.
    """
    return apply_zpl_darkness(apply_zpl_offsets(zpl, cfg), cfg)
