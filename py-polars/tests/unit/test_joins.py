from __future__ import annotations

import typing
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

import polars as pl
import polars.testing

if TYPE_CHECKING:
    from polars.internals.type_aliases import JoinStrategy


def test_semi_anti_join() -> None:
    df_a = pl.DataFrame({"key": [1, 2, 3], "payload": ["f", "i", None]})

    df_b = pl.DataFrame({"key": [3, 4, 5, None]})

    assert df_a.join(df_b, on="key", how="anti").to_dict(False) == {
        "key": [1, 2],
        "payload": ["f", "i"],
    }
    assert df_a.join(df_b, on="key", how="semi").to_dict(False) == {
        "key": [3],
        "payload": [None],
    }

    # lazy
    assert df_a.lazy().join(df_b.lazy(), on="key", how="anti").collect().to_dict(
        False
    ) == {
        "key": [1, 2],
        "payload": ["f", "i"],
    }
    assert df_a.lazy().join(df_b.lazy(), on="key", how="semi").collect().to_dict(
        False
    ) == {
        "key": [3],
        "payload": [None],
    }

    df_a = pl.DataFrame(
        {"a": [1, 2, 3, 1], "b": ["a", "b", "c", "a"], "payload": [10, 20, 30, 40]}
    )

    df_b = pl.DataFrame({"a": [3, 3, 4, 5], "b": ["c", "c", "d", "e"]})

    assert df_a.join(df_b, on=["a", "b"], how="anti").to_dict(False) == {
        "a": [1, 2, 1],
        "b": ["a", "b", "a"],
        "payload": [10, 20, 40],
    }
    assert df_a.join(df_b, on=["a", "b"], how="semi").to_dict(False) == {
        "a": [3],
        "b": ["c"],
        "payload": [30],
    }


def test_join_same_cat_src() -> None:
    df = pl.DataFrame(
        data={"column": ["a", "a", "b"], "more": [1, 2, 3]},
        schema=[("column", pl.Categorical), ("more", pl.Int32)],
    )
    df_agg = df.groupby("column").agg(pl.col("more").mean())
    assert df.join(df_agg, on="column").to_dict(False) == {
        "column": ["a", "a", "b"],
        "more": [1, 2, 3],
        "more_right": [1.5, 1.5, 3.0],
    }


def test_sorted_merge_joins() -> None:
    for reverse in [False, True]:
        n = 30
        df_a = pl.DataFrame(
            {"a": np.sort(np.random.randint(0, n // 2, n))}
        ).with_row_count("row_a")

        df_b = pl.DataFrame(
            {"a": np.sort(np.random.randint(0, n // 2, n // 2))}
        ).with_row_count("row_b")

        if reverse:
            df_a = df_a.select(pl.all().reverse())
            df_b = df_b.select(pl.all().reverse())

        join_strategies: list[JoinStrategy] = ["left", "inner"]
        for cast_to in [int, str, float]:
            for how in join_strategies:
                df_a_ = df_a.with_column(pl.col("a").cast(cast_to))
                df_b_ = df_b.with_column(pl.col("a").cast(cast_to))

                # hash join
                out_hash_join = df_a_.join(df_b_, on="a", how=how)

                # sorted merge join
                out_sorted_merge_join = df_a_.with_column(
                    pl.col("a").set_sorted(reverse)
                ).join(
                    df_b_.with_column(pl.col("a").set_sorted(reverse)), on="a", how=how
                )

                assert out_hash_join.frame_equal(out_sorted_merge_join)


def test_join_negative_integers() -> None:
    expected = {"a": [-6, -1, 0], "b": [-6, -1, 0]}

    df1 = pl.DataFrame(
        {
            "a": [-1, -6, -3, 0],
        }
    )

    df2 = pl.DataFrame(
        {
            "a": [-6, -1, -4, -2, 0],
            "b": [-6, -1, -4, -2, 0],
        }
    )

    for dt in [pl.Int8, pl.Int16, pl.Int32, pl.Int64]:
        assert (
            df1.with_column(pl.all().cast(dt))
            .join(df2.with_column(pl.all().cast(dt)), on="a", how="inner")
            .to_dict(False)
            == expected
        )


def test_join_asof_floats() -> None:
    df1 = pl.DataFrame({"a": [1.0, 2.0, 3.0], "b": ["lrow1", "lrow2", "lrow3"]})
    df2 = pl.DataFrame({"a": [0.59, 1.49, 2.89], "b": ["rrow1", "rrow2", "rrow3"]})
    assert df1.join_asof(df2, on="a", strategy="backward").to_dict(False) == {
        "a": [1.0, 2.0, 3.0],
        "b": ["lrow1", "lrow2", "lrow3"],
        "b_right": ["rrow1", "rrow2", "rrow3"],
    }

    # with by argument
    # 5740
    df1 = pl.DataFrame(
        {"b": np.linspace(0, 5, 7), "c": ["x" if i < 4 else "y" for i in range(7)]}
    )
    df2 = pl.DataFrame(
        {
            "val": [0, 2.5, 2.6, 2.7, 3.4, 4, 5],
            "c": ["x", "x", "x", "y", "y", "y", "y"],
        }
    ).with_column(pl.col("val").alias("b"))
    assert df1.join_asof(df2, on="b", by="c").to_dict(False) == {
        "b": [
            0.0,
            0.8333333333333334,
            1.6666666666666667,
            2.5,
            3.3333333333333335,
            4.166666666666667,
            5.0,
        ],
        "c": ["x", "x", "x", "x", "y", "y", "y"],
        "val": [0.0, 0.0, 0.0, 2.5, 2.7, 4.0, 5.0],
    }


def test_join_asof_tolerance() -> None:
    df_trades = pl.DataFrame(
        {
            "time": [
                datetime(2020, 1, 1, 9, 0, 1),
                datetime(2020, 1, 1, 9, 0, 1),
                datetime(2020, 1, 1, 9, 0, 3),
                datetime(2020, 1, 1, 9, 0, 6),
            ],
            "stock": ["A", "B", "B", "C"],
            "trade": [101, 299, 301, 500],
        }
    )

    df_quotes = pl.DataFrame(
        {
            "time": [
                datetime(2020, 1, 1, 9, 0, 0),
                datetime(2020, 1, 1, 9, 0, 2),
                datetime(2020, 1, 1, 9, 0, 4),
                datetime(2020, 1, 1, 9, 0, 6),
            ],
            "stock": ["A", "B", "C", "A"],
            "quote": [100, 300, 501, 102],
        }
    )

    assert df_trades.join_asof(
        df_quotes, on="time", by="stock", tolerance="2s"
    ).to_dict(False) == {
        "time": [
            datetime(2020, 1, 1, 9, 0, 1),
            datetime(2020, 1, 1, 9, 0, 1),
            datetime(2020, 1, 1, 9, 0, 3),
            datetime(2020, 1, 1, 9, 0, 6),
        ],
        "stock": ["A", "B", "B", "C"],
        "trade": [101, 299, 301, 500],
        "quote": [100, None, 300, 501],
    }

    assert df_trades.join_asof(
        df_quotes, on="time", by="stock", tolerance="1s"
    ).to_dict(False) == {
        "time": [
            datetime(2020, 1, 1, 9, 0, 1),
            datetime(2020, 1, 1, 9, 0, 1),
            datetime(2020, 1, 1, 9, 0, 3),
            datetime(2020, 1, 1, 9, 0, 6),
        ],
        "stock": ["A", "B", "B", "C"],
        "trade": [101, 299, 301, 500],
        "quote": [100, None, 300, None],
    }


def test_join_asof_tolerance_forward() -> None:
    df_quotes = pl.DataFrame(
        {
            "time": [
                datetime(2020, 1, 1, 9, 0, 0),
                datetime(2020, 1, 1, 9, 0, 2),
                datetime(2020, 1, 1, 9, 0, 4),
                datetime(2020, 1, 1, 9, 0, 6),
                datetime(2020, 1, 1, 9, 0, 7),
            ],
            "stock": ["A", "B", "C", "A", "D"],
            "quote": [100, 300, 501, 102, 10],
        }
    )

    df_trades = pl.DataFrame(
        {
            "time": [
                datetime(2020, 1, 1, 9, 0, 2),
                datetime(2020, 1, 1, 9, 0, 1),
                datetime(2020, 1, 1, 9, 0, 3),
                datetime(2020, 1, 1, 9, 0, 6),
                datetime(2020, 1, 1, 9, 0, 7),
            ],
            "stock": ["A", "B", "B", "C", "D"],
            "trade": [101, 299, 301, 500, 10],
        }
    )

    assert df_quotes.join_asof(
        df_trades, on="time", by="stock", tolerance="2s", strategy="forward"
    ).to_dict(False) == {
        "time": [
            datetime(2020, 1, 1, 9, 0, 0),
            datetime(2020, 1, 1, 9, 0, 2),
            datetime(2020, 1, 1, 9, 0, 4),
            datetime(2020, 1, 1, 9, 0, 6),
            datetime(2020, 1, 1, 9, 0, 7),
        ],
        "stock": ["A", "B", "C", "A", "D"],
        "quote": [100, 300, 501, 102, 10],
        "trade": [101, 301, 500, None, 10],
    }

    assert df_quotes.join_asof(
        df_trades, on="time", by="stock", tolerance="1s", strategy="forward"
    ).to_dict(False) == {
        "time": [
            datetime(2020, 1, 1, 9, 0, 0),
            datetime(2020, 1, 1, 9, 0, 2),
            datetime(2020, 1, 1, 9, 0, 4),
            datetime(2020, 1, 1, 9, 0, 6),
            datetime(2020, 1, 1, 9, 0, 7),
        ],
        "stock": ["A", "B", "C", "A", "D"],
        "quote": [100, 300, 501, 102, 10],
        "trade": [None, 301, None, None, 10],
    }

    # Sanity check that this gives us equi-join
    assert df_quotes.join_asof(
        df_trades, on="time", by="stock", tolerance="0s", strategy="forward"
    ).to_dict(False) == {
        "time": [
            datetime(2020, 1, 1, 9, 0, 0),
            datetime(2020, 1, 1, 9, 0, 2),
            datetime(2020, 1, 1, 9, 0, 4),
            datetime(2020, 1, 1, 9, 0, 6),
            datetime(2020, 1, 1, 9, 0, 7),
        ],
        "stock": ["A", "B", "C", "A", "D"],
        "quote": [100, 300, 501, 102, 10],
        "trade": [None, None, None, None, 10],
    }


def test_deprecated() -> None:
    df = pl.DataFrame({"a": [1, 2], "b": [3, 4]})
    other = pl.DataFrame({"a": [1, 2], "c": [3, 4]})
    result = pl.DataFrame({"a": [1, 2], "b": [3, 4], "c": [3, 4]})

    np.testing.assert_equal(df.join(other=other, on="a").to_numpy(), result.to_numpy())
    np.testing.assert_equal(
        df.lazy().join(other=other.lazy(), on="a").collect().to_numpy(),
        result.to_numpy(),
    )


def test_join_on_expressions() -> None:
    df_a = pl.DataFrame({"a": [1, 2, 3]})

    df_b = pl.DataFrame({"b": [1, 4, 9, 9, 0]})

    assert df_a.join(df_b, left_on=(pl.col("a") ** 2).cast(int), right_on=pl.col("b"))[
        "a"
    ].to_list() == [1, 4, 9, 9]


def test_join() -> None:
    df_left = pl.DataFrame(
        {
            "a": ["a", "b", "a", "z"],
            "b": [1, 2, 3, 4],
            "c": [6, 5, 4, 3],
        }
    )
    df_right = pl.DataFrame(
        {
            "a": ["b", "c", "b", "a"],
            "k": [0, 3, 9, 6],
            "c": [1, 0, 2, 1],
        }
    )

    joined = df_left.join(df_right, left_on="a", right_on="a").sort("a")
    assert joined["b"].series_equal(pl.Series("b", [1, 3, 2, 2]))

    joined = df_left.join(df_right, left_on="a", right_on="a", how="left").sort("a")
    assert joined["c_right"].is_null().sum() == 1
    assert joined["b"].series_equal(pl.Series("b", [1, 3, 2, 2, 4]))

    joined = df_left.join(df_right, left_on="a", right_on="a", how="outer").sort("a")
    assert joined["c_right"].null_count() == 1
    assert joined["c"].null_count() == 1
    assert joined["b"].null_count() == 1
    assert joined["k"].null_count() == 1
    assert joined["a"].null_count() == 0

    # we need to pass in a column to join on, either by supplying `on`, or both
    # `left_on` and `right_on`
    with pytest.raises(ValueError):
        df_left.join(df_right)
    with pytest.raises(ValueError):
        df_left.join(df_right, right_on="a")
    with pytest.raises(ValueError):
        df_left.join(df_right, left_on="a")

    df_a = pl.DataFrame({"a": [1, 2, 1, 1], "b": ["a", "b", "c", "c"]})
    df_b = pl.DataFrame(
        {"foo": [1, 1, 1], "bar": ["a", "c", "c"], "ham": ["let", "var", "const"]}
    )

    # just check if join on multiple columns runs
    df_a.join(df_b, left_on=["a", "b"], right_on=["foo", "bar"])
    eager_join = df_a.join(df_b, left_on="a", right_on="foo")
    lazy_join = df_a.lazy().join(df_b.lazy(), left_on="a", right_on="foo").collect()

    cols = ["a", "b", "bar", "ham"]
    assert lazy_join.shape == eager_join.shape
    assert lazy_join.sort(by=cols).frame_equal(eager_join.sort(by=cols))


def test_joins_dispatch() -> None:
    # this just flexes the dispatch a bit

    # don't change the data of this dataframe, this triggered:
    # https://github.com/pola-rs/polars/issues/1688
    dfa = pl.DataFrame(
        {
            "a": ["a", "b", "c", "a"],
            "b": [1, 2, 3, 1],
            "date": ["2021-01-01", "2021-01-02", "2021-01-03", "2021-01-01"],
            "datetime": [13241324, 12341256, 12341234, 13241324],
        }
    ).with_columns(
        [pl.col("date").str.strptime(pl.Date), pl.col("datetime").cast(pl.Datetime)]
    )

    join_strategies: list[JoinStrategy] = ["left", "inner", "outer"]
    for how in join_strategies:
        dfa.join(dfa, on=["a", "b", "date", "datetime"], how=how)
        dfa.join(dfa, on=["date", "datetime"], how=how)
        dfa.join(dfa, on=["date", "datetime", "a"], how=how)
        dfa.join(dfa, on=["date", "a"], how=how)
        dfa.join(dfa, on=["a", "datetime"], how=how)
        dfa.join(dfa, on=["date"], how=how)


def test_join_on_cast() -> None:
    df_a = (
        pl.DataFrame({"a": [-5, -2, 3, 3, 9, 10]})
        .with_row_count()
        .with_column(pl.col("a").cast(pl.Int32))
    )

    df_b = pl.DataFrame({"a": [-2, -3, 3, 10]})

    assert df_a.join(df_b, on=pl.col("a").cast(pl.Int64)).to_dict(False) == {
        "row_nr": [1, 2, 3, 5],
        "a": [-2, 3, 3, 10],
    }
    assert df_a.lazy().join(
        df_b.lazy(), on=pl.col("a").cast(pl.Int64)
    ).collect().to_dict(False) == {"row_nr": [1, 2, 3, 5], "a": [-2, 3, 3, 10]}


def test_asof_join_projection_resolution_4606() -> None:
    a = pl.DataFrame({"a": [1], "b": [2], "c": [3]}).lazy()
    b = pl.DataFrame({"a": [1], "b": [2], "d": [4]}).lazy()
    joined_tbl = a.join_asof(b, on="a", by="b")
    assert joined_tbl.groupby("a").agg(
        [pl.col("c").sum().alias("c")]
    ).collect().columns == ["a", "c"]


def test_join_chunks_alignment_4720() -> None:
    df1 = pl.DataFrame(
        {
            "index1": pl.arange(0, 2, eager=True),
            "index2": pl.arange(10, 12, eager=True),
        }
    )

    df2 = pl.DataFrame(
        {
            "index3": pl.arange(100, 102, eager=True),
        }
    )

    df3 = pl.DataFrame(
        {
            "index1": pl.arange(0, 2, eager=True),
            "index2": pl.arange(10, 12, eager=True),
            "index3": pl.arange(100, 102, eager=True),
        }
    )
    assert (
        df1.join(df2, how="cross").join(
            df3,
            on=["index1", "index2", "index3"],
            how="left",
        )
    ).to_dict(False) == {
        "index1": [0, 0, 1, 1],
        "index2": [10, 10, 11, 11],
        "index3": [100, 101, 100, 101],
    }

    assert (
        df1.join(df2, how="cross").join(
            df3,
            on=["index3", "index1", "index2"],
            how="left",
        )
    ).to_dict(False) == {
        "index1": [0, 0, 1, 1],
        "index2": [10, 10, 11, 11],
        "index3": [100, 101, 100, 101],
    }


def test_sorted_flag_after_joins() -> None:
    np.random.seed(1)
    dfa = pl.DataFrame(
        {
            "a": np.random.randint(0, 13, 20),
            "b": np.random.randint(0, 13, 20),
        }
    ).sort("a")

    dfb = pl.DataFrame(
        {
            "a": np.random.randint(0, 13, 10),
            "b": np.random.randint(0, 13, 10),
        }
    )

    dfapd = dfa.to_pandas()
    dfbpd = dfb.to_pandas()

    def test_with_pd(
        dfa: pd.DataFrame, dfb: pd.DataFrame, on: str, how: str, joined: pl.DataFrame
    ) -> None:
        a = (
            dfa.merge(
                dfb,
                on=on,
                how=how,  # type: ignore[arg-type]
                suffixes=("", "_right"),
            )
            .sort_values(["a", "b"])
            .reset_index(drop=True)
        )
        b = joined.sort(["a", "b"]).to_pandas()
        pd.testing.assert_frame_equal(a, b)

    joined = dfa.join(dfb, on="b", how="left")
    assert joined["a"].flags["SORTED_ASC"]
    test_with_pd(dfapd, dfbpd, "b", "left", joined)

    joined = dfa.join(dfb, on="b", how="inner")
    assert joined["a"].flags["SORTED_ASC"]
    test_with_pd(dfapd, dfbpd, "b", "inner", joined)

    joined = dfa.join(dfb, on="b", how="semi")
    assert joined["a"].flags["SORTED_ASC"]
    joined = dfa.join(dfb, on="b", how="semi")
    assert joined["a"].flags["SORTED_ASC"]

    joined = dfb.join(dfa, on="b", how="left")
    assert not joined["a"].flags["SORTED_ASC"]
    test_with_pd(dfbpd, dfapd, "b", "left", joined)

    joined = dfb.join(dfa, on="b", how="inner")
    assert not joined["a"].flags["SORTED_ASC"]

    joined = dfb.join(dfa, on="b", how="semi")
    assert not joined["a"].flags["SORTED_ASC"]
    joined = dfb.join(dfa, on="b", how="anti")
    assert not joined["a"].flags["SORTED_ASC"]


@typing.no_type_check
def test_jit_sort_joins() -> None:
    n = 200
    dfa = pd.DataFrame(
        {
            "a": np.random.randint(0, 100, n),
            "b": np.arange(0, n),
        }
    )

    n = 40
    dfb = pd.DataFrame(
        {
            "a": np.random.randint(0, 100, n),
            "b": np.arange(0, n),
        }
    )
    dfa_pl = pl.from_pandas(dfa).sort("a")
    dfb_pl = pl.from_pandas(dfb)

    for how in ["left", "inner"]:
        pd_result = dfa.merge(dfb, on="a", how=how)
        pd_result.columns = ["a", "b", "b_right"]

        # left key sorted right is not
        pl_result = dfa_pl.join(dfb_pl, on="a", how=how).sort(["a", "b"])

        a = pl.from_pandas(pd_result).with_column(pl.all().cast(int)).sort(["a", "b"])
        assert a.frame_equal(pl_result, null_equal=True)
        assert pl_result["a"].flags["SORTED_ASC"]

        # left key sorted right is not
        pd_result = dfb.merge(dfa, on="a", how=how)
        pd_result.columns = ["a", "b", "b_right"]
        pl_result = dfb_pl.join(dfa_pl, on="a", how=how).sort(["a", "b"])

        a = pl.from_pandas(pd_result).with_column(pl.all().cast(int)).sort(["a", "b"])
        assert a.frame_equal(pl_result, null_equal=True)
        assert pl_result["a"].flags["SORTED_ASC"]


def test_asof_join_schema_5211() -> None:
    df1 = pl.DataFrame({"today": [1, 2]})

    df2 = pl.DataFrame({"next_friday": [1, 2]})

    assert (
        df1.lazy()
        .join_asof(
            df2.lazy(), left_on="today", right_on="next_friday", strategy="forward"
        )
        .schema
    ) == {"today": pl.Int64, "next_friday": pl.Int64}


def test_asof_join_schema_5684() -> None:
    df_a = pl.DataFrame(
        {
            "id": [1],
            "a": [1],
            "b": [1],
        }
    ).lazy()

    df_b = pl.DataFrame(
        {
            "id": [1, 1, 2],
            "b": [3, -3, 6],
        }
    ).lazy()

    q = (
        df_a.join_asof(df_b, by="id", left_on="a", right_on="b")
        .drop("b")
        .join_asof(df_b, by="id", left_on="a", right_on="b")
        .drop("b")
    )

    projected_result = q.select(pl.all()).collect()
    result = q.collect()

    assert projected_result.frame_equal(result)
    assert (
        q.schema
        == projected_result.schema
        == {"id": pl.Int64, "a": pl.Int64, "b_right": pl.Int64}
    )


@typing.no_type_check
def test_streaming_joins() -> None:
    n = 100
    dfa = pd.DataFrame(
        {
            "a": np.random.randint(0, 40, n),
            "b": np.arange(0, n),
        }
    )

    n = 100
    dfb = pd.DataFrame(
        {
            "a": np.random.randint(0, 40, n),
            "b": np.arange(0, n),
        }
    )
    dfa_pl = pl.from_pandas(dfa).sort("a")
    dfb_pl = pl.from_pandas(dfb)

    for how in ["inner", "left"]:
        pd_result = dfa.merge(dfb, on="a", how=how)
        pd_result.columns = ["a", "b", "b_right"]

        pl_result = (
            dfa_pl.lazy()
            .join(dfb_pl.lazy(), on="a", how=how)
            .sort(["a", "b"])
            .collect(streaming=True)
        )

        a = pl.from_pandas(pd_result).with_column(pl.all().cast(int)).sort(["a", "b"])
        pl.testing.assert_frame_equal(a, pl_result, check_dtype=False)

        pd_result = dfa.merge(dfb, on=["a", "b"], how=how)

        pl_result = (
            dfa_pl.lazy()
            .join(dfb_pl.lazy(), on=["a", "b"], how=how)
            .sort(["a", "b"])
            .collect(streaming=True)
        )

        # we cast to integer because pandas joins creates floats
        a = pl.from_pandas(pd_result).with_column(pl.all().cast(int)).sort(["a", "b"])
        pl.testing.assert_frame_equal(a, pl_result, check_dtype=False)


def test_join_asof_projection() -> None:
    df1 = pl.DataFrame(
        {
            "df1_date": [20221011, 20221012, 20221013, 20221014, 20221016],
            "df1_col1": ["foo", "bar", "foo", "bar", "foo"],
            "key": ["a", "b", "b", "a", "b"],
        }
    )

    df2 = pl.DataFrame(
        {
            "df2_date": [20221012, 20221015, 20221018],
            "df2_col1": ["1", "2", "3"],
            "key": ["a", "b", "b"],
        }
    )

    assert (
        (
            df1.lazy().join_asof(df2.lazy(), left_on="df1_date", right_on="df2_date")
        ).select([pl.col("df2_date"), "df1_date"])
    ).collect().to_dict(False) == {
        "df2_date": [None, 20221012, 20221012, 20221012, 20221015],
        "df1_date": [20221011, 20221012, 20221013, 20221014, 20221016],
    }
    assert (
        df1.lazy().join_asof(
            df2.lazy(), by="key", left_on="df1_date", right_on="df2_date"
        )
    ).select(["df2_date", "df1_date"]).collect().to_dict(False) == {
        "df2_date": [None, None, None, 20221012, 20221015],
        "df1_date": [20221011, 20221012, 20221013, 20221014, 20221016],
    }


def test_asof_join_by_logical_types() -> None:
    dates = (
        pl.date_range(datetime(2022, 1, 1), datetime(2022, 1, 2), interval="2h")
        .cast(pl.Datetime("ns"))
        .head(9)
    )
    x = pl.DataFrame({"a": dates, "b": map(float, range(9)), "c": ["1", "2", "3"] * 3})
    assert x.join_asof(x, on="b", by=["c", "a"]).to_dict(False) == {
        "a": [
            datetime(2022, 1, 1, 0, 0),
            datetime(2022, 1, 1, 2, 0),
            datetime(2022, 1, 1, 4, 0),
            datetime(2022, 1, 1, 6, 0),
            datetime(2022, 1, 1, 8, 0),
            datetime(2022, 1, 1, 10, 0),
            datetime(2022, 1, 1, 12, 0),
            datetime(2022, 1, 1, 14, 0),
            datetime(2022, 1, 1, 16, 0),
        ],
        "b": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
        "c": ["1", "2", "3", "1", "2", "3", "1", "2", "3"],
    }


def test_join_panic_on_binary_expr_5915() -> None:
    df_a = pl.DataFrame({"a": [1, 2, 3]}).lazy()
    df_b = pl.DataFrame({"b": [1, 4, 9, 9, 0]}).lazy()

    z = df_a.join(df_b, left_on=[(pl.col("a") + 1).cast(int)], right_on=[pl.col("b")])
    assert z.collect().to_dict(False) == {"a": [4]}
