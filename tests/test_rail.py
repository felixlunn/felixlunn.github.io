import pandas as pd
import pytest

from whips.sources import rail

ORR = (
    '"Table 1410: Passenger entries, exits and interchanges by station, Great Britain, annual data, April 2024 to March 2025",,\n'
    'This worksheet contains one table.,,\n'
    'Station name,"Entries and exits: \nAll tickets",Interchanges\n'
    'Alpha,"1,000",0\nBeta [note 1],"2,000",0\nGamma,500,0\nWitham,300,0\nLincoln,200,0\n'
)
NAPTAN = (
    "ATCOCode,CommonName,StopType,Status,Longitude,Latitude,Easting,Northing\n"
    "9100A,Alpha Rail Station,RLY,active,0.5,0.5,,\n"
    "9100B,Beta,RLY,active,1.5,0.5,,\n"
    "9100G,Gamma Rail Station,RLY,inactive,0.5,0.5,,\n"       # inactive: ignored
    "9100W,Witham (Essex) Rail Station,RLY,active,0.6,0.6,,\n"  # matched without the bracket
    "9100L,Lincoln Central Rail Station,RLY,active,1.6,0.6,,\n" # matched by unique prefix
)
GEO = {"type": "FeatureCollection", "features": [
    {"properties": {"code": "E1"}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
    {"properties": {"code": "E2"}, "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]}},
    {"properties": {"code": "S3"}, "geometry": {"type": "Polygon", "coordinates": [[[5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]}},
    {"properties": {"code": "N4"}, "geometry": {"type": "Polygon", "coordinates": [[[7, 7], [8, 7], [8, 8], [7, 8], [7, 7]]]}},
]}


def test_parse_locate_and_seat_frames():
    stations, period = rail.parse_orr(ORR)
    assert period == "April 2024 to March 2025"
    assert stations.set_index("name")["journeys"].to_dict() == {"Alpha": 1000, "Beta [note 1]": 2000, "Gamma": 500, "Witham": 300, "Lincoln": 200}
    located = rail.locate(stations, rail.parse_naptan(NAPTAN), GEO)
    assert located.set_index("name")["pcon"].to_dict() == {"Alpha": "E1", "Beta [note 1]": "E2", "Witham": "E1", "Lincoln": "E2"}
    f = rail.seat_frames(located, pd.Series({"E1": 130.0, "E2": 220.0}), ["E1", "E2", "S3", "N4"])
    per = f["rail_journeys_per_resident"]
    assert (per["num"] / per["den"]).to_dict() == pytest.approx({"E1": 10.0, "E2": 10.0})
    n = f["rail_stations"]
    assert (n["num"] / n["den"]).to_dict() == {"E1": 2, "E2": 2, "S3": 0}  # GB only: no value for Northern Ireland
