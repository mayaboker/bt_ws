import time
from numbers import Real


class PID:
    def __init__(self, kp, ki, kd, kf=0.0, output_limits=None):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.kf = kf
        self.output_min = None
        self.output_max = None
        self.set_output_limits(output_limits)
        self.integral = 0
        self.prev_error = 0
        self.last_time = None

    def set_gains(self, kp, ki, kd, kf=None, output_limits=None):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        if kf is not None:
            self.kf = kf
        if output_limits is not None:
            self.set_output_limits(output_limits)

    def set_output_limits(self, output_limits=None):
        if output_limits is None:
            self.output_min = None
            self.output_max = None
            return

        if isinstance(output_limits, Real) and not isinstance(output_limits, bool):
            limit = abs(output_limits)
            self.output_min = -limit
            self.output_max = limit
            return

        if not isinstance(output_limits, tuple) or len(output_limits) != 2:
            raise TypeError("output_limits must be a number or a tuple of two numbers")

        self.output_min, self.output_max = output_limits
        for limit in output_limits:
            if limit is not None and (
                not isinstance(limit, Real) or isinstance(limit, bool)
            ):
                raise TypeError("output_limits tuple values must be numbers")

        if (
            self.output_min is not None
            and self.output_max is not None
            and self.output_min > self.output_max
        ):
            raise ValueError("output minimum cannot be greater than output maximum")

    def reset(self):
        self.integral = 0
        self.prev_error = 0
        self.last_time = None

    def update(self, target, current, feed_forward=0.0) -> float:
        now = time.monotonic()
        error = target - current

        if self.last_time is None:
            dt = 0.0
            derivative = 0.0
        else:
            dt = now - self.last_time
            derivative = (error - self.prev_error) / dt if dt > 0.0 else 0.0

        self.integral += error * dt

        output = (
            self.kp * error +
            self.ki * self.integral +
            self.kd * derivative +
            self.kf * feed_forward
        )
        if self.output_min is not None and output < self.output_min:
            output = self.output_min
        elif self.output_max is not None and output > self.output_max:
            output = self.output_max

        self.prev_error = error
        self.last_time = now
        return output
