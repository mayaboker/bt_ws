from queue import Queue

class TrackerManager:
    """
    Manages the lifecycle of trackers and their associated resources.
    """

    def __init__(self):
        self.result_queue = Queue()


    def update_tracker(self, tracker_id: str, result: dict):
        """
        Updates the tracker with the given ID with the provided result.
        If the tracker does not exist, it will be created.
        """
        self.result_queue.put((tracker_id, result))

    def get_result(self):
        """
        Retrieves the latest result from the result queue.
        Returns a tuple containing (tracker_id, result).
        """
        results = []
        while not self.result_queue.empty():
            results.append(self.result_queue.get())
        return results[-1:]
