"""Splitting artist credits into individual artists.

The interesting cases are all about restraint: separators that look decisive
until you meet a band whose name contains one.
"""

from vibenative import artists


def idx(*names):
    """An index built from names that each appear as a whole credit."""
    return artists.build_index(names)


# --- unambiguous separators -------------------------------------------------


def test_slash_splits():
    assert artists.split_credit("Smoakland/Heyz") == ["Smoakland", "Heyz"]


def test_comma_splits():
    assert artists.split_credit("AC Slater, Scrufizzer") == ["AC Slater", "Scrufizzer"]


def test_three_way_slash():
    assert artists.split_credit("Apashe/Vanic/lia") == ["Apashe", "Vanic", "lia"]


def test_feat_variants_all_split():
    for sep in ("feat.", "feat", "ft.", "ft", "featuring", "Feat."):
        assert artists.split_credit(f"Afrojack {sep} Miss Palmer") == ["Afrojack", "Miss Palmer"]


def test_vs_splits():
    assert artists.split_credit("Alpha vs. Beta") == ["Alpha", "Beta"]


def test_presents_splits():
    assert artists.split_credit("Sasha presents Xpander") == ["Sasha", "Xpander"]


def test_plain_name_is_left_alone():
    assert artists.split_credit("Deadmau5") == ["Deadmau5"]


def test_empty_credit_yields_nothing():
    assert artists.split_credit("") == []
    assert artists.split_credit(None) == []


def test_duplicates_are_collapsed_case_insensitively():
    # "A & B feat. a" names two artists, not three.
    assert artists.split_credit("Skrillex/SKRILLEX/Diplo") == ["Skrillex", "Diplo"]


# --- punctuation inside a name ----------------------------------------------


def test_attested_act_with_a_slash_is_kept_whole():
    """ "AC/DC" keeps turning up whole and "AC" and "DC" never turn up alone."""
    i = artists.build_index(["AC/DC"] * 4 + ["Smoakland/Heyz"])
    assert artists.split_credit("AC/DC", i) == ["AC/DC"]
    assert artists.split_credit("AC/DC feat. Axl", i) == ["AC/DC", "Axl"]
    # The one-off collaboration in the same library still splits.
    assert artists.split_credit("Smoakland/Heyz", i) == ["Smoakland", "Heyz"]


def test_attested_act_with_a_comma_is_kept_whole():
    i = artists.build_index(["Tyler, The Creator"] * 3)
    assert artists.split_credit("Tyler, The Creator", i) == ["Tyler, The Creator"]


def test_frequent_pairing_still_splits_when_a_half_records_alone():
    i = artists.build_index(["AC Slater/Chris Lorenzo"] * 5 + ["Chris Lorenzo"])
    assert artists.split_credit("AC Slater/Chris Lorenzo", i) == ["AC Slater", "Chris Lorenzo"]


def test_without_an_index_punctuation_always_splits():
    assert artists.split_credit("AC/DC") == ["AC", "DC"]


# --- the ampersand rule -----------------------------------------------------


def test_duo_is_kept_whole_when_neither_half_stands_alone():
    """The case that makes a naive split worse than none at all."""
    i = idx("Above & Beyond", "Above & Beyond", "Marsh")
    assert artists.split_credit("Above & Beyond", i) == ["Above & Beyond"]


def test_duo_survives_as_part_of_a_larger_credit():
    i = idx("Above & Beyond", "Above & Beyond", "Marsh")
    assert artists.split_credit("Above & Beyond/Marsh", i) == ["Above & Beyond", "Marsh"]


def test_collaboration_splits_when_a_half_records_alone():
    i = idx("Excision", "Excision", "Dion Timmer", "Excision & Dion Timmer")
    assert artists.split_credit("Excision & Dion Timmer", i) == ["Excision", "Dion Timmer"]


def test_common_pairing_outranks_a_known_half():
    """A real duo stays whole even if something by a same-named solo act exists."""
    i = artists.build_index(
        ["Chase & Status"] * 6 + ["Chase"],
    )
    assert artists.split_credit("Chase & Status", i) == ["Chase & Status"]


def test_without_an_index_ampersands_are_never_split():
    """No library evidence means no guessing -- the safe subset only."""
    assert artists.split_credit("Excision & Dion Timmer") == ["Excision & Dion Timmer"]


# --- separators that hide inside real names ---------------------------------


def test_with_does_not_split_a_band_name():
    """'Fly With Us' is one act; treating "with" as unambiguous made it two."""
    i = idx("Fly With Us", "Fly With Us", "AC Slater")
    assert artists.split_credit("AC Slater/Fly With Us", i) == ["AC Slater", "Fly With Us"]


def test_with_splits_when_both_sides_are_known_artists():
    i = idx("Sub Focus", "Sub Focus", "Wilkinson", "Sub Focus with Wilkinson")
    assert artists.split_credit("Sub Focus with Wilkinson", i) == ["Sub Focus", "Wilkinson"]


def test_x_splits_only_with_evidence():
    known = idx("Justice", "Justice", "Tame Impala", "Justice x Tame Impala")
    assert artists.split_credit("Justice x Tame Impala", known) == ["Justice", "Tame Impala"]
    # An unknown pairing is left alone rather than guessed at.
    assert artists.split_credit("Malcolm x Friends") == ["Malcolm x Friends"]


def test_plus_is_evidence_tested_too():
    i = idx("Above", "Above", "Beyond", "Above + Beyond")
    assert artists.split_credit("Above + Beyond", i) == ["Above", "Beyond"]
    assert artists.split_credit("Above + Beyond") == ["Above + Beyond"]


# --- index ------------------------------------------------------------------


def test_build_index_counts_hard_split_parts():
    i = artists.build_index(["A/B", "B, C", "B"])
    assert i["B"] == 3
    assert i["A"] == 1
    assert i["C"] == 1
    # The joined forms are counted too, so an act like "AC/DC" can be told
    # apart from a pairing.
    assert i["A/B"] == 1
    assert i["B, C"] == 1


def test_build_index_does_not_split_ampersands():
    i = artists.build_index(["Above & Beyond"])
    assert i == {"Above & Beyond": 1}
