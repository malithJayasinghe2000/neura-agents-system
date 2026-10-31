"""The Marketing calendar's dates, worked out in code (ADR-0072 §2, §3, §5).

What these hold, without a database:

* **The rule dates** fall where the ADR says (Black Friday is the day after the
  fourth Thursday of November; Mother's Day the second Sunday of May; payday the
  last Monday to Friday of each month), checked against the approved boards'
  2027 days.
* **The moving dates are never written from memory** (AD12): the hand-checked
  list is empty, so each shows *Date not set yet* until FiveNeurals or the owner
  sets it.
* **What is kept**: nothing suggested before the year's list is saved; an own
  date from the moment it is added; *every year* repeats it.
* **A shop elsewhere** gets the shopping days only (R85).
* **Days in the shop's time** (G119).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from neura_agent_core.calendar import (
    MOVING_DAYS,
    SUGGESTED,
    SUGGESTED_BY_KEY,
    Country,
    DateRow,
    Group,
    Plan,
    PlanState,
    add_months,
    black_friday,
    kept_occurrences,
    last_working_day,
    post_days,
    shop_today,
    suggested_for,
    this_years_list,
    year_saved,
)


def _saved(year: int, *, unticked: tuple[str, ...] = (), days: dict[str, date] | None = None):
    """A saved year: a row per suggested key, ticked unless named."""
    return [
        DateRow(
            id=f"cal_{year}_{s.key}",
            year=year,
            key=s.key,
            name=None,
            day=(days or {}).get(s.key),
            kept=s.key not in unticked,
        )
        for s in SUGGESTED
    ]


def _own(name: str, day: date, *, every_year: bool = False, kept: bool = True) -> DateRow:
    return DateRow(
        id=f"cal_own_{name}",
        year=day.year,
        key=None,
        name=name,
        day=day,
        kept=kept,
        every_year=every_year,
    )


class TestTheRuleDates:
    def test_the_boards_2027_days(self) -> None:
        """Board 77 (This year's dates · 2027): May 9, Nov 26, Nov 29."""
        assert SUGGESTED_BY_KEY["mothers_day"].days(2027) == (date(2027, 5, 9),)
        assert SUGGESTED_BY_KEY["black_friday"].days(2027) == (date(2027, 11, 26),)
        assert SUGGESTED_BY_KEY["cyber_monday"].days(2027) == (date(2027, 11, 29),)
        assert SUGGESTED_BY_KEY["valentines_day"].days(2027) == (date(2027, 2, 14),)
        assert SUGGESTED_BY_KEY["eleven_eleven"].days(2027) == (date(2027, 11, 11),)
        assert SUGGESTED_BY_KEY["christmas"].days(2027) == (date(2027, 12, 25),)

    def test_black_friday_is_the_day_after_the_fourth_thursday(self) -> None:
        assert black_friday(2026) == date(2026, 11, 27)
        # November 2029 starts on a Thursday: the 22nd is the fourth.
        assert black_friday(2029) == date(2029, 11, 23)

    def test_payday_is_the_last_monday_to_friday(self) -> None:
        assert last_working_day(2027, 3) == date(2027, 3, 31)  # board 75: Mar 31
        assert last_working_day(2027, 4) == date(2027, 4, 30)  # board 75: Apr 30
        assert last_working_day(2026, 1) == date(2026, 1, 30)  # the 31st is a Saturday
        assert last_working_day(2026, 5) == date(2026, 5, 29)  # the 31st is a Sunday
        assert last_working_day(2026, 12) == date(2026, 12, 31)
        assert len(SUGGESTED_BY_KEY["payday"].days(2026)) == 12

    def test_the_moving_dates_are_left_unset(self) -> None:
        """AD12: written in by hand each January, never from memory."""
        assert MOVING_DAYS == {}
        moving = [s.key for s in SUGGESTED if s.moving]
        assert moving == ["avurudu", "vesak", "poson", "deepavali", "eid_al_fitr"]
        for key in moving:
            assert SUGGESTED_BY_KEY[key].days(2027) == ()


class TestTheList:
    def test_the_lists_as_the_board_orders_them(self) -> None:
        names = {g: [s.name for s in SUGGESTED if s.group is g] for g in Group}
        assert names[Group.FESTIVALS] == [
            "Avurudu",
            "Vesak",
            "Poson",
            "Deepavali",
            "Ramadan and Eid al-Fitr",
            "Christmas",
        ]
        assert names[Group.MONTHLY] == ["Payday"]
        assert names[Group.SHOPPING] == [
            "Valentine's Day",
            "Mother's Day",
            "11.11",
            "Black Friday",
            "Cyber Monday",
        ]

    def test_a_shop_elsewhere_gets_the_shopping_days_only(self) -> None:
        assert {s.group for s in suggested_for(Country.OTHER)} == {Group.SHOPPING}
        assert len(suggested_for(Country.SRI_LANKA)) == len(SUGGESTED)

    def test_a_year_never_saved_shows_every_date_ticked(self) -> None:
        choices, own = this_years_list([], 2027)
        assert all(c.kept for c in choices)
        assert own == []
        by_key = {c.suggested.key: c for c in choices}
        assert by_key["black_friday"].day == date(2027, 11, 26)
        assert by_key["vesak"].day is None  # Date not set yet
        assert by_key["payday"].day is None  # twelve days, none on the right

    def test_the_owner_sets_a_moving_date(self) -> None:
        rows = _saved(2027, days={"vesak": date(2027, 5, 20)}, unticked=("black_friday",))
        by_key = {c.suggested.key: c for c in this_years_list(rows, 2027)[0]}
        assert by_key["vesak"].day == date(2027, 5, 20)
        assert by_key["vesak"].set_by_owner
        assert not by_key["black_friday"].kept


class TestWhatIsKept:
    START = date(2027, 3, 24)
    END = add_months(START, 12)

    def test_nothing_suggested_is_kept_before_the_year_is_saved(self) -> None:
        own = _own("Our big sale", date(2027, 6, 20))
        found = kept_occurrences([own], Country.SRI_LANKA, start=self.START, end=self.END)
        assert [o.name for o in found] == ["Our big sale"]
        assert not year_saved([own], 2027)

    def test_a_saved_year_keeps_the_ticked_dates_soonest_first(self) -> None:
        rows = _saved(2027, unticked=("black_friday",))
        found = kept_occurrences(rows, Country.SRI_LANKA, start=self.START, end=self.END)
        names = [o.name for o in found]
        assert "Black Friday" not in names
        assert names[:4] == ["Payday", "Avurudu", "Payday", "Mother's Day"]
        # Avurudu is not set: it sits at the end of its usual month, as board 75
        # places Vesak (by name beside April's payday on the 30th).
        assert found[1].day is None and found[2].day == date(2027, 4, 30)

    def test_a_moving_date_not_set_is_listed_until_its_months_pass(self) -> None:
        rows = _saved(2027)
        later = kept_occurrences(
            rows, Country.SRI_LANKA, start=date(2027, 7, 1), end=date(2027, 12, 31)
        )
        names = {o.name for o in later}
        assert "Vesak" not in names and "Poson" not in names
        assert "Deepavali" in names  # usually October or November

    def test_payday_twelve_times(self) -> None:
        rows = _saved(2027)
        found = kept_occurrences(
            rows, Country.SRI_LANKA, start=date(2027, 1, 1), end=date(2028, 1, 1)
        )
        assert sum(o.key == "payday" for o in found) == 12

    def test_a_shop_elsewhere_keeps_no_festival(self) -> None:
        rows = _saved(2027)
        found = kept_occurrences(rows, Country.OTHER, start=self.START, end=self.END)
        assert {o.key for o in found} == {
            "mothers_day",
            "eleven_eleven",
            "black_friday",
            "cyber_monday",
        }

    def test_every_year_repeats_and_a_one_off_does_not(self) -> None:
        rows = [
            _own("Birthday", date(2026, 6, 20), every_year=True),
            _own("Launch", date(2026, 6, 21)),
            _own("Unticked", date(2027, 6, 22), kept=False),
        ]
        found = kept_occurrences(rows, Country.SRI_LANKA, start=self.START, end=self.END)
        assert [(o.name, o.day) for o in found] == [("Birthday", date(2027, 6, 20))]

    def test_the_29th_of_february_falls_on_the_28th(self) -> None:
        leap = _own("Leap", date(2028, 2, 29), every_year=True)
        assert leap.own_day(2029) == date(2029, 2, 28)

    def test_the_next_year_is_kept_only_once_saved(self) -> None:
        rows = _saved(2026)
        found = kept_occurrences(
            rows, Country.SRI_LANKA, start=date(2026, 12, 1), end=date(2027, 12, 1)
        )
        assert {o.year for o in found} == {2026}


class TestTimeAndPlans:
    def test_days_are_counted_in_the_shops_time(self) -> None:
        late = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)  # 01:30 on Nov 1 in Colombo
        assert shop_today(Country.SRI_LANKA, late) == date(2026, 11, 1)
        assert shop_today(Country.OTHER, late) == date(2026, 10, 31)

    def test_when_to_post(self) -> None:
        """Board 76: Avurudu on April 14; Mar 31, Apr 7, Apr 12."""
        assert post_days(date(2027, 4, 14)) == {
            "teaser": date(2027, 3, 31),
            "launch": date(2027, 4, 7),
            "last_chance": date(2027, 4, 12),
        }

    def test_a_plan_shows_the_owners_words_over_the_models(self) -> None:
        plan = Plan(
            id="pln_1",
            date_key="s:avurudu",
            day=date(2027, 4, 14),
            name="Avurudu",
            answer={"texts": {"teaser": "AI words", "banner": "AI banner"}},
            edits={"teaser": "My words"},
        )
        assert plan.texts()["teaser"] == "My words"
        assert plan.texts()["banner"] == "AI banner"
        assert plan.state is PlanState.READY

    def test_a_plan_that_never_passed_the_checks_failed(self) -> None:
        plan = Plan(id="p", date_key="o:x", day=date(2027, 1, 1), name="X", answer=None)
        assert plan.state is PlanState.FAILED

    def test_months_on_the_last_day(self) -> None:
        assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
        assert add_months(date(2026, 11, 1), 12) == date(2027, 11, 1)
