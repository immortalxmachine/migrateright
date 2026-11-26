"""Profiling measures, and proof that src/profile.py does not shadow the stdlib module."""

import pandas as pd

from src import profile as profiling


def test_stdlib_profile_module_still_importable():
    import cProfile
    import profile as stdlib_profile

    assert hasattr(stdlib_profile, "Profile")        # the standard library module, not ours
    assert profiling.__name__ == "src.profile"
    cProfile.run("sum(range(10))", None)             # cProfile uses the stdlib 'profile' too


def test_shape():
    assert profiling.shape("SW1A 1AA") == "AA9A 9AA"


def test_profile_measures(rules):
    df = pd.DataFrame({"KUNNR": ["1", "2", "3", "4"], "NAME1": ["A", None, "C", "C"],
                       "EMAIL": ["a@x.example", "bad", None, None],
                       "LAND1": ["GB", "UK", "GB", "DE"]}, dtype=object)
    p = profiling.profile_dataframe(df, "customer", rules).set_index("field")
    assert p.loc["NAME1", "filled_pct"] == 75.0
    assert p.loc["NAME1", "distinct"] == 2
    assert p.loc["NAME1", "mandatory"] == "Y"
    assert p.loc["EMAIL", "validity_pct"] == 50.0
    assert p.loc["LAND1", "validity_pct"] == 75.0    # 'UK' is not an allowed code before mapping
