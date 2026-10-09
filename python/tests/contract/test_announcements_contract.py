from realtime_core import parse_inbound


def test_events_parse_as_event_frames(announcements_fixture):
    events = announcements_fixture["events"]
    state = parse_inbound(events["state"])
    assert state is not None and state.event == "announcement.state"
    assert state.payload["announcements"][0]["scope"] == "platform"
    upsert = parse_inbound(events["upsert"])
    assert upsert is not None and upsert.event == "announcement.upsert"
    assert upsert.payload["id"] == "01J9ZK3Q7M8N2P4R6S8T0V2W4X"
    clear = parse_inbound(events["clear"])
    assert clear is not None and clear.payload == {"id": "01J9ZK3Q7M8N2P4R6S8T0V2W4X", "scope": "platform"}
