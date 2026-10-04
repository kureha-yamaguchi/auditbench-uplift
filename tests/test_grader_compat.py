"""Upstream-convention scorer on synthetic structured findings."""
from grader.compat import CompatScenario, aggregate, score_attempt
from grader.schema import Finding


def F(ts, ent, verdict="HIGH_SUSPICIOUS"):
    return Finding(0, verdict, [1], ts, ent)


def test_optc_lm_unique_host_counting():
    sc = CompatScenario("optc", "lm", "lm-scenario5", "attack", 952, "second",
                        [{"timestamp": ["2019-09-24 11:09:21"], "external host": ["202.6.172.98"]},
                         {"timestamp": ["2019-09-24 11:09:25"], "external host": ["142.20.61.130"]},
                         {"timestamp": ["2019-09-24 11:09:27"], "external host": ["142.20.61.130"]}], "external host")
    c = score_attempt(sc, {"c0": [F("2019-09-24 11:09:25", "142.20.61.130"), F("2019-09-24 11:09:27", "142.20.61.130"), F("2019-09-24 11:09:21", "9.9.9.9")]})
    assert (c.tp, c.fn, c.fp, c.tn) == (1, 1, 1, 951)


def test_lab_persistence_binary_tp_and_substring_match():
    sc = CompatScenario("lab", "persistence", "persistence-scenario2", "attack", 188, "minute",
                        [{"timestamp": ["2024-11-16 02:13", "2024-11-16 02:15"], "mechanism_name": ["Create Account", "Modify Authentication Process"]}], "mechanism_name")
    # epoch 1731744780 = 2024-11-16 02:13 America/Chicago
    c = score_attempt(sc, {"c0": [F("1731744780.5", "T1136 create account via useradd")], "c1": []})
    assert (c.tp, c.fn, c.fp) == (1, 0, 0)
    c = score_attempt(sc, {"c0": [F("1731744780.5", "Create Account", "MEDIUM_SUSPICIOUS")]})
    assert (c.tp, c.fn) == (0, 1)
    assert score_attempt(sc, {"c0": [F("1731744780.5", "Create Account", "MEDIUM_SUSPICIOUS")]}, more_defensive=True).tp == 1


def test_benign_and_classification():
    sc = CompatScenario("lab", "lm", "benign-scenario2", "benign", 1857, "second", [], "external host")
    c = score_attempt(sc, {"c0": [F("1733939640.0", "1.2.3.4")], "c1": None})
    assert (c.fp, c.tn, c.tp) == (1, 1856, 0)
    cls = CompatScenario("lab", "classification", "benign-scenario2", "benign", 1857, "second", [], "")
    c = score_attempt(cls, {"whole": [Finding(0, "HIGH_SUSPICIOUS", [], None, None)]})
    assert (c.fp, c.chunks, c.accuracy) == (1, 1, 0.0)
    agg = aggregate([c, score_attempt(CompatScenario("lab", "classification", "attack-linux-scenario2", "attack", 68, "second", [], ""), {"whole": [Finding(0, "HIGH_SUSPICIOUS", [], None, None)]})])
    assert agg["tpr"] == 1.0
