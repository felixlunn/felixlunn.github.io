from whips.sources.debates import parse_events, topics_for


def ev(i, day, cat, title, typ="Main Chamber", sort=0, time="", **kw):
    return {"Id": i, "StartDate": f"{day}T00:00:00", "StartTime": time, "Type": typ, "Category": cat,
            "Description": title, "SortOrder": sort, "Members": kw.get("members", []), "CancelledDate": kw.get("cancelled")}


def test_keeps_debates_drops_questions_and_statements():
    events = [
        ev(1, "2026-11-03", "Oral questions", "Home Office"),
        ev(2, "2026-11-03", "Prime Minister's Question Time", ""),
        ev(3, "2026-11-03", "Business Statement", "Business Questions"),
        ev(4, "2026-11-03", "Ten Minute Rule Motion", "That leave be given"),
        ev(5, "2026-11-03", "Westminster Hall debate", "The matter of  anti-social\r\nbehaviour", typ="Westminster Hall",
           members=[{"Name": "A MP", "Party": "Liberal Democrat", "MemberFrom": "Somewhere"}]),
        ev(6, "2026-11-03", "Adjournment", "Cancelled one", cancelled="2026-11-01"),
        ev(7, "2026-11-04", "Opposition Day Debate", "Opposition Day"),
    ]
    out = parse_events(events)
    assert [d["id"] for d in out] == [5, 7]
    assert out[0]["title"] == "The matter of anti-social behaviour"
    assert out[0]["topics"] == ["policing"]
    assert out[0]["members"] == [{"name": "A MP", "party": "Liberal Democrat", "constituency": "Somewhere"}]


def test_only_first_private_members_bills_each_friday_in_order():
    events = [ev(i, "2026-11-13", "Private Members' Bills", f"Bill {i}", sort=i, time="09:30" if i == 1 else "")
              for i in range(6, 0, -1)]
    assert [d["title"] for d in parse_events(events)] == ["Bill 1", "Bill 2", "Bill 3"]


def test_topic_keywords():
    assert topics_for("Impact of heating oil prices on rural areas") == ["energy", "rural"]
    assert topics_for("Access to dental care in the East of England") == ["health"]
    assert "housing" not in topics_for("Support for parents of disabled children")  # "parent" is not "rent"
    assert "transport" not in topics_for("Aid spending abroad")  # "abroad" is not "road"
    assert topics_for("General Debate on the Nolan principles") == []
