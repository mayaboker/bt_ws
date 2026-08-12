from bt_app.trackers.tracker_manager import TrackerManager, TrackerSnapshot


def test_get_result_returns_none_before_first_update():
    manager = TrackerManager()

    assert manager.get_result() is None


def test_get_result_does_not_remove_latest_result():
    manager = TrackerManager()
    result = {"frame_id": 1}
    manager.update_tracker("primary", result, received_at_s=12.5)

    expected = TrackerSnapshot("primary", result, 12.5)
    assert manager.get_result() == expected
    assert manager.get_result() == expected


def test_new_result_replaces_existing_result():
    manager = TrackerManager()
    manager.update_tracker("first", {"frame_id": 1}, received_at_s=1.0)
    replacement = {"frame_id": 2}

    manager.update_tracker("second", replacement, received_at_s=2.0)

    assert manager.get_result() == TrackerSnapshot("second", replacement, 2.0)


def test_clear_discards_retained_snapshot():
    manager = TrackerManager()
    manager.update_tracker("primary", {"frame_id": 1}, received_at_s=1.0)

    manager.clear()

    assert manager.get_result() is None
