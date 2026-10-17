"""The drawing helpers: log-scale score bars, the fingerprint fill order, the hands."""
from goodix550c_tui import art
from goodix550c_tui.parsers import FINGERS


def test_score_pos_is_log_and_clamped():
    assert art.score_pos(0) == 0.0 and art.score_pos(art.SCORE_LO) == 0.0
    assert art.score_pos(10 ** 9) == 1.0
    # equal ratios -> equal steps: 150->1500 is as long as 1500->15000
    a, b, c = art.score_pos(150), art.score_pos(1500), art.score_pos(15000)
    assert abs((b - a) - (c - b)) < 1e-9
    # the old linear scale hid 150-1300 next to a 33915; on a log scale they are well apart
    assert art.score_pos(1300) - art.score_pos(150) > 0.25
    assert art.score_pos(33915) < 1.0


def test_score_bar_marks_threshold_and_colours_by_result():
    w = 40
    mark = int(art.score_pos(150) * w)
    miss = art.score_bar(97, w, art.RED)
    hit = art.score_bar(1300, w, art.GREEN)
    big = art.score_bar(33915, w, art.GREEN)
    retry = art.score_bar(None, w, art.ORANGE)
    for bar in (miss, hit, big, retry):
        assert bar.cell_len == w
    assert miss.plain[mark] == "│" and hit.plain[mark] == "┃"
    assert "█" not in miss.plain[mark:] and "█" in hit.plain[mark + 1:]
    assert hit.plain.count("·") > big.plain.count("·")      # bigger score, longer bar
    assert set(retry.plain) <= {"·", "│"}
    assert any(art.RED in str(s.style) for s in miss.spans)
    assert any(art.GREEN in str(s.style) for s in hit.spans)
    axis = art.score_axis(w)
    assert axis.plain[mark:mark + 3] == "150" and "1k" in axis.plain


def test_score_columns_size_and_threshold_line():
    rows = art.score_columns([(300, art.GREEN), (None, art.ORANGE), (90, art.RED)], 30, 6)
    assert len(rows) == 6 and all(r.cell_len == 30 for r in rows)
    assert any("150" in r.plain and "╌" in r.plain for r in rows)
    assert "•" in rows[-1].plain


def test_fingerprint_fill_lights_from_the_core_outward():
    masks, keys = art.print_model(30, 16)
    lit = [k for row in keys for k in row]
    assert min(lit) >= 0 and max(lit) <= 1.0
    centre_key = keys[7][15]
    edge_key = max(keys[r][c] for r in range(16) for c in range(30) if masks[r][c])
    assert centre_key < 0.3 < edge_key
    empty = art.fingerprint_lines(0.0, "#00ff00", "#111111")
    full = art.fingerprint_lines(1.0, "#00ff00", "#111111")
    assert len(empty) == 16 and [l.plain for l in empty] == [l.plain for l in full]
    assert not any("#00ff00" in str(s.style) for l in empty for s in l.spans)
    assert not any("#111111" in str(s.style) for l in full for s in l.spans)
    sizes = [art.print_size(w, h) for w, h in ((40, 30), (80, 45), (20, 10))]
    assert all(c >= 10 and r >= 6 for c, r in sizes)


def test_big_number_and_word():
    n = art.big_number("83%", art.GREEN)
    assert len(n) == 3 and all(r.cell_len == art.big_number_width("83%") for r in n)
    assert n[2].plain.endswith("%")
    assert len(art.big_word("PRESS", art.GREEN)) == 5
    assert len(art.big_word("PRESS", art.GREEN, half=True)) == 3
    assert art.big_word_width("TRY AGAIN") == 61


def test_hands_show_saved_and_selected():
    for big in (False, True):
        lines = art.hands_lines({"right-thumb"}, "left-index-finger", big=big)
        w, h = art.hands_size(big)
        assert len(lines) == h and all(l.cell_len == w for l in lines)
        text = "\n".join(l.plain for l in lines)
        assert "LEFT HAND" in text and "RIGHT HAND" in text
        assert text.count("●") == 1 and text.count("○") == len(FINGERS) - 1
        assert any(art.BLUE in str(s.style) for l in lines for s in l.spans)
