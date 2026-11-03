from whips.sources.pupils import headline_rows


class FakeDS:
    meta = {"filters": [{"options": [{"id": "T", "label": "Total"}, {"id": "M", "label": "State-funded mainstream schools"},
                                     {"id": "S", "label": "State-funded mainstream and special"}, {"id": "F", "label": "FSM eligible"},
                                     {"id": "N", "label": "Not recorded as a sustained destination"}]}]}


def test_headline_rows_only_all_pupil_mainstream_rows():
    rows = [{"filters": {"a": "M", "b": "T", "c": "N"}}, {"filters": {"a": "M", "b": "F", "c": "N"}},
            {"filters": {"a": "S", "b": "T", "c": "N"}}]
    assert headline_rows(FakeDS(), rows) == [rows[0]]
