"""Logger rev 2.1: the recorder firmware's '#SSL16 T ...' status line is parsed into a dict."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "software", "python"))

gui = pytest.importorskip("ssl16_buzzer_gui")   # needs tkinter + matplotlib; skipped where they are missing


def _source():
    s = gui.SerialSource.__new__(gui.SerialSource)   # no serial port needed for the parser
    s.status = {}
    return s


def test_status_line_is_parsed():
    s = _source()
    s._scan_text(b"junk#SSL16 T ms=1200 temp=26.1250 seq=118 sd=ok rec=E1_P07_r1_142233 rec_kb=1500 "
                 b"ring_drop=0 usb_drop=0 sd_err=0 i2s_ovf=0\nmore")
    assert s.status["rec"] == "E1_P07_r1_142233"
    assert s.status["sd"] == "ok"
    assert s.status["ring_drop"] == "0"
    assert s.status["i2s_ovf"] == "0"
    assert float(s.status["temp"]) == pytest.approx(26.125)


def test_incomplete_line_is_ignored():
    s = _source()
    s._scan_text(b"#SSL16 T ms=1200 temp=26.1")      # no newline yet: keep the previous status
    assert s.status == {}


def test_run_fields_extended_but_backward_compatible():
    old = ["run_id", "time", "experiment", "point", "rep", "wav", "flag", "flag_reason", "notes"]
    assert all(f in gui.RUN_FIELDS for f in old)
    assert all(f in gui.RUN_FIELDS for f in ["sd_wav", "sd_seen", "sd_ring_drop", "sd_err", "i2s_ovf", "board_temp_c"])
