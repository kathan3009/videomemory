"""Unit tests for the visual funnel's pure logic (no model / network needed)."""

from __future__ import annotations

import numpy as np

from videomemory import visual_index as vi


def test_hamming():
    assert vi._hamming(0b0000, 0b0000) == 0
    assert vi._hamming(0b1010, 0b0000) == 2
    assert vi._hamming(0b1111, 0b0000) == 4


def test_wants_ocr_routes_text_queries_to_separate():
    assert vi._wants_ocr("read the text on the slide")
    assert vi._wants_ocr("what does the error message say")
    assert not vi._wants_ocr("when does the person jump")
    assert not vi._wants_ocr("a wide shot of mountains")


def test_mmr_picks_relevant_then_diverse():
    # Two near-identical high-scorers + one distinct lower-scorer.
    vecs = np.array([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]], dtype=np.float32)
    scores = np.array([0.9, 0.89, 0.5], dtype=np.float32)
    picks = vi._mmr(scores, vecs, lam=0.6, k=2)
    # Top relevance is index 0; MMR's second pick should be the diverse #2, not the near-dup #1.
    assert picks[0] == 0
    assert picks[1] == 2


def test_frame_sig_distinguishes_flat_colors(tmp_path):
    from PIL import Image

    red = tmp_path / "red.jpg"
    blue = tmp_path / "blue.jpg"
    Image.new("RGB", (64, 48), (255, 0, 0)).save(red)
    Image.new("RGB", (64, 48), (0, 0, 255)).save(blue)
    hr, mr = vi._frame_sig(red)
    hb, mb = vi._frame_sig(blue)
    # Flat frames share a degenerate dHash (0) — mean color is what separates them.
    assert hr == hb == 0
    assert float(np.abs(mr - mb).sum()) > 100.0


def test_pts_regex_parses_showinfo():
    sample = (
        "[Parsed_showinfo_2 @ 0x] n:0 pts:0 pts_time:0 duration:1\n"
        "[Parsed_showinfo_2 @ 0x] n:1 pts:1000 pts_time:5.04 duration:1\n"
    )
    assert vi._PTS_RE.findall(sample) == ["0", "5.04"]
