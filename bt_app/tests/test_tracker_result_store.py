from bt_msgs import TrackerResultMessage

from bt_app.services import TrackerResultStore


def message(frame_id: int, tracker_id: int = 1) -> TrackerResultMessage:
    return TrackerResultMessage(frame_id=frame_id, timestamp_ns=frame_id, tracker_id=tracker_id)


def test_store_keeps_latest_frame_and_records_local_receive_time():
    times = iter((1.0, 2.0, 3.0))
    store = TrackerResultStore(clock=lambda: next(times))
    store.process_tracker_result(message(2))
    store.process_tracker_result(message(1))
    assert store.latest_observation.result.frame_id == 2
    assert store.latest_observation.received_at_s == 1.0


def test_store_accepts_restarted_frame_sequence_for_new_tracker_id():
    store = TrackerResultStore(clock=lambda: 1.0)
    store.process_tracker_result(message(100, tracker_id=1))
    store.process_tracker_result(message(1, tracker_id=2))
    assert store.latest_observation.result.tracker_id == 2
    assert store.latest_observation.result.frame_id == 1
