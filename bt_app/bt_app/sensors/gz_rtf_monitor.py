#!/usr/bin/env python3

import argparse
import os
import signal
import subprocess
import time

import gz.transport13 as gz_transport
from gz.msgs10 import world_stats_pb2
from loguru import logger


DEFAULT_STATS_TOPIC = "/stats"
DEFAULT_WORLD = "betaloop_iris_betaflight_demo_harmonic.sdf"
DEFAULT_PLUGIN_PATH = "/home/user/projects/aeroloop_gazebo/plugins/build"
DEFAULT_RESOURCE_PATH = (
    "/home/user/projects/aeroloop_gazebo/models:"
    "/home/user/projects/aeroloop_gazebo/worlds"
)


class GazeboRtfMonitor:
    """Subscribe to Gazebo world stats and print real-time factor."""

    def __init__(self, *, stats_topic=DEFAULT_STATS_TOPIC, print_period_s=1.0):
        self.stats_topic = stats_topic
        self.print_period_s = print_period_s
        self.node = gz_transport.Node()
        self.last_print_time = 0.0
        self.latest_stats = None

    def start(self):
        subscribed = self.node.subscribe(
            world_stats_pb2.WorldStatistics,
            self.stats_topic,
            self._on_stats,
        )
        if subscribed is False:
            raise RuntimeError(f"Failed to subscribe to Gazebo stats topic {self.stats_topic}")

        logger.info("Subscribed to Gazebo stats topic {}", self.stats_topic)

    def spin(self, stop_flag):
        self.start()
        while not stop_flag["stop"]:
            time.sleep(0.1)

    def _on_stats(self, msg):
        self.latest_stats = msg
        now = time.monotonic()
        if now - self.last_print_time < self.print_period_s:
            return

        self.last_print_time = now
        sim_time_s = msg.sim_time.sec + (msg.sim_time.nsec * 1e-9)
        real_time_s = msg.real_time.sec + (msg.real_time.nsec * 1e-9)
        print(
            f"rtf={msg.real_time_factor:.3f} "
            f"sim_time={sim_time_s:.2f}s "
            f"real_time={real_time_s:.2f}s "
            f"iterations={msg.iterations} "
            f"paused={msg.paused}",
            flush=True,
        )


class GazeboServerProcess:
    """Launch and stop Gazebo in server-only mode."""

    def __init__(
        self,
        *,
        world=DEFAULT_WORLD,
        gz_bin="gz",
        verbose=4,
        plugin_path=DEFAULT_PLUGIN_PATH,
        resource_path=DEFAULT_RESOURCE_PATH,
    ):
        self.world = world
        self.gz_bin = gz_bin
        self.verbose = verbose
        self.plugin_path = plugin_path
        self.resource_path = resource_path
        self.process = None

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return

        env = os.environ.copy()
        env["GZ_SIM_SYSTEM_PLUGIN_PATH"] = prepend_env_path(
            self.plugin_path,
            env.get("GZ_SIM_SYSTEM_PLUGIN_PATH"),
        )
        env["GZ_SIM_RESOURCE_PATH"] = prepend_env_path(
            self.resource_path,
            env.get("GZ_SIM_RESOURCE_PATH"),
        )

        cmd = [
            self.gz_bin,
            "sim",
            "-s",
            "-v",
            str(self.verbose),
            "-r",
            self.world,
        ]
        logger.info("Starting Gazebo server: {}", " ".join(cmd))
        self.process = subprocess.Popen(cmd, env=env)

    def stop(self, timeout=5.0):
        if self.process is None or self.process.poll() is not None:
            return

        logger.info("Stopping Gazebo server")
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("Gazebo server did not stop after terminate; killing it")
            self.process.kill()
            self.process.wait(timeout=timeout)


def prepend_env_path(value, existing):
    if not value:
        return existing or ""
    if not existing:
        return value
    return f"{value}:{existing}"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run Gazebo server and/or print RTF from the /stats topic."
    )
    parser.add_argument("--stats-topic", default=DEFAULT_STATS_TOPIC)
    parser.add_argument("--period", type=float, default=1.0)
    parser.add_argument(
        "--run-server",
        action="store_true",
        help="Start gz sim in server-only mode before subscribing to stats.",
    )
    parser.add_argument("--world", default=DEFAULT_WORLD)
    parser.add_argument("--gz-bin", default="gz")
    parser.add_argument("--verbose", type=int, default=4)
    parser.add_argument("--plugin-path", default=DEFAULT_PLUGIN_PATH)
    parser.add_argument("--resource-path", default=DEFAULT_RESOURCE_PATH)
    return parser.parse_args()


def main():
    args = parse_args()
    stop_flag = {"stop": False}
    server = None

    def stop_handler(signum, _frame):
        logger.info("Stopping RTF monitor after signal {}", signum)
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    if args.run_server:
        server = GazeboServerProcess(
            world=args.world,
            gz_bin=args.gz_bin,
            verbose=args.verbose,
            plugin_path=args.plugin_path,
            resource_path=args.resource_path,
        )
        server.start()

    try:
        monitor = GazeboRtfMonitor(
            stats_topic=args.stats_topic,
            print_period_s=args.period,
        )
        monitor.spin(stop_flag)
    finally:
        if server is not None:
            server.stop()


if __name__ == "__main__":
    main()
