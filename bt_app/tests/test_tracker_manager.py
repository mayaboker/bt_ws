from bt_app.trackers.tracker_manager import TrackerManager


def test_get_result_returns_none_before_first_update():
    manager = TrackerManager()

    assert manager.get_result() is None


def test_get_result_does_not_remove_latest_result():
    manager = TrackerManager()
    result = {"frame_id": 1}
    manager.update_tracker("primary", result)

    assert manager.get_result() == ("primary", result)
    assert manager.get_result() == ("primary", result)


def test_new_result_replaces_existing_result():
    manager = TrackerManager()
    manager.update_tracker("first", {"frame_id": 1})
    replacement = {"frame_id": 2}

    manager.update_tracker("second", replacement)

    assert manager.get_result() == ("second", replacement)
