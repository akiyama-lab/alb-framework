#!/usr/bin/env python3

import json
import threading

import rclpy
from autoware_adapi_v1_msgs.msg import OperationModeState
from autoware_vehicle_msgs.msg import VelocityReport
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py import message_to_yaml
from tier4_vehicle_msgs.msg import ActuationStatusStamped
from visualization_msgs.msg import MarkerArray


class AutowareTopicCapture(Node):
    def __init__(self):
        super().__init__("autoware_topic_capture")

        # フィルター設定を初期化
        self.filters = {
            "velocity_threshold": 0.1,  # m/s以下の速度をフィルター
            "acceleration_threshold": 0.1,  # m/s^2以下の加速度をフィルター
            "trajectory_enable": True,
            "control_command_enable": True,
            "obstacle_stop_enable": True,
            "obstacle_cruise_enable": True,
            "obstacle_slow_down_enable": True,
            "actuation_status_enable": True,
            "operation_mode_enable": True,
        }

        self.get_logger().info("Filters: " + json.dumps(self.filters, indent=2))

        # 各条件の初回触発フラグ
        self._obstacle_stop_triggered = False
        self._obstacle_cruise_triggered = False
        self._obstacle_slow_down_triggered = False
        self._accel_zero_triggered = False
        self._brake_triggered = False
        self._decel_started_triggered = False
        self._autonomous_mode_triggered = False
        self._prev_velocity = None

        # ノード実行状態フラグ
        self._is_running = False

        # キャプチャしたトピック情報を保存（最新値）
        self._captured_topics = {
            "decelerate": None,
            "obstacle_stop": None,
            "obstacle_cruise": None,
            "obstacle_slow_down": None,
            "accel_zero": None,
            "brake": None,
            "autonomous_mode": None,
        }
        # 時系列で保存するイベントログ (ns, name, concat_ts)
        self._captured_events = []

        # obstacle_stop 仮想壁（MarkerArray）
        self.create_subscription(
            MarkerArray,
            "/planning/scenario_planning/lane_driving/motion_planning/motion_velocity_planner/obstacle_stop/virtual_walls",
            self.obstacle_stop_callback,
            10,
        )

        # obstacle_cruise 仮想壁（MarkerArray）
        self.create_subscription(
            MarkerArray,
            "/planning/scenario_planning/lane_driving/motion_planning/motion_velocity_planner/obstacle_cruise/virtual_walls",
            self.obstacle_cruise_callback,
            10,
        )

        # obstacle_slow_down 仮想壁（MarkerArray）
        self.create_subscription(
            MarkerArray,
            "/planning/scenario_planning/lane_driving/motion_planning/motion_velocity_planner/obstacle_slow_down/virtual_walls",
            self.obstacle_slow_down_callback,
            10,
        )

        # アクチュエーションステータス（アクセル/ブレーキ）
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.create_subscription(
            ActuationStatusStamped,
            "/vehicle/status/actuation_status",
            self.actuation_status_callback,
            qos,
        )

        # 速度ステータス（減速判定用）
        self.create_subscription(
            VelocityReport,
            "/vehicle/status/velocity_status",
            self.velocity_status_callback,
            qos,
        )

        # オペレーションモード（自動運転開始検出用）
        self.create_subscription(
            OperationModeState,
            "/system/operation_mode/state",
            self.operation_mode_callback,
            10,
        )

        self.get_logger().info("Autoware Topic Capture Node initialized!")

    def set_filter(self, filter_name: str, value):
        """フィルター値を動的に設定"""
        if filter_name in self.filters:
            self.filters[filter_name] = value
            self.get_logger().info(f"Filter updated: {filter_name} = {value}")
        else:
            self.get_logger().warn(f"Filter not found: {filter_name}")

    def reset_triggers(self):
        """すべてのトリガーフラグをリセット"""
        self._obstacle_stop_triggered = False
        self._obstacle_cruise_triggered = False
        self._obstacle_slow_down_triggered = False
        self._accel_zero_triggered = False
        self._brake_triggered = False
        self._decel_started_triggered = False
        self._autonomous_mode_triggered = False
        self._prev_velocity = None

        # キャプチャ情報もリセット
        for key in self._captured_topics:
            self._captured_topics[key] = None
        self._captured_events.clear()

    def _format_timestamp(self, sec, nanosec):
        return f"{sec}{nanosec:09d}"

    def _to_ns(self, sec, nanosec):
        return sec * 1_000_000_000 + nanosec

    # obstacle_stop が出たトピックをキャプチャ
    def obstacle_stop_callback(self, msg: MarkerArray):
        if not self._is_running or not self.filters["obstacle_stop_enable"]:
            return

        self.get_logger().debug(f"[obstacle_stop] Received {len(msg.markers)} markers")
        for i, marker in enumerate(msg.markers):
            marker_text = getattr(marker, "text", "")
            self.get_logger().debug(
                f'  Marker {i}: ns={marker.ns}, text="{marker_text}"'
            )
            if marker_text == "obstacle stop":
                if not self._obstacle_stop_triggered:
                    print("[obstacle_stop/virtual_walls] first match")
                    print("---")
                    print(message_to_yaml(marker))
                    ts = self._format_timestamp(
                        marker.header.stamp.sec, marker.header.stamp.nanosec
                    )
                    self._captured_topics["obstacle_stop"] = ts
                    self._captured_events.append(
                        (
                            self._to_ns(
                                marker.header.stamp.sec, marker.header.stamp.nanosec
                            ),
                            "obstacle_stop",
                            ts,
                        )
                    )
                    self._obstacle_stop_triggered = True
                else:
                    self.get_logger().debug(
                        f"obstacle_stop already triggered (flag={self._obstacle_stop_triggered})"
                    )

    # obstacle_cruise が出たトピックをキャプチャ
    def obstacle_cruise_callback(self, msg: MarkerArray):
        if not self._is_running or not self.filters["obstacle_cruise_enable"]:
            return

        self.get_logger().debug(
            f"[obstacle_cruise] Received {len(msg.markers)} markers"
        )
        for i, marker in enumerate(msg.markers):
            marker_text = getattr(marker, "text", "")
            self.get_logger().debug(
                f'  Marker {i}: ns={marker.ns}, text="{marker_text}"'
            )
            if marker_text == "obstacle cruise":
                if not self._obstacle_cruise_triggered:
                    print("[obstacle_cruise/virtual_walls] first match")
                    print("---")
                    print(message_to_yaml(marker))
                    ts = self._format_timestamp(
                        marker.header.stamp.sec, marker.header.stamp.nanosec
                    )
                    self._captured_topics["obstacle_cruise"] = ts
                    self._captured_events.append(
                        (
                            self._to_ns(
                                marker.header.stamp.sec, marker.header.stamp.nanosec
                            ),
                            "obstacle_cruise",
                            ts,
                        )
                    )
                    self._obstacle_cruise_triggered = True
                else:
                    self.get_logger().debug(
                        f"obstacle_cruise already triggered (flag={self._obstacle_cruise_triggered})"
                    )

    # obstacle_slow_down が出たトピックをキャプチャ
    def obstacle_slow_down_callback(self, msg: MarkerArray):
        if not self._is_running or not self.filters["obstacle_slow_down_enable"]:
            return

        self.get_logger().debug(
            f"[obstacle_slow_down] Received {len(msg.markers)} markers"
        )
        for i, marker in enumerate(msg.markers):
            marker_text = getattr(marker, "text", "")
            self.get_logger().debug(
                f'  Marker {i}: ns={marker.ns}, text="{marker_text}"'
            )
            if marker_text == "obstacle slow down":
                if not self._obstacle_slow_down_triggered:
                    print("[obstacle_slow_down/virtual_walls] first match")
                    print("---")
                    print(message_to_yaml(marker))
                    ts = self._format_timestamp(
                        marker.header.stamp.sec, marker.header.stamp.nanosec
                    )
                    self._captured_topics["obstacle_slow_down"] = ts
                    self._captured_events.append(
                        (
                            self._to_ns(
                                marker.header.stamp.sec, marker.header.stamp.nanosec
                            ),
                            "obstacle_slow_down",
                            ts,
                        )
                    )
                    self._obstacle_slow_down_triggered = True
                else:
                    self.get_logger().debug(
                        "obstacle_slow_down already triggered (flag=True)"
                    )

    # アクセル0/ブレーキ起動のタイミングを出力
    def actuation_status_callback(self, msg: ActuationStatusStamped):
        if not self._is_running or not self.filters["actuation_status_enable"]:
            return

        status = msg.status
        accel = getattr(status, "accel_status", None)
        brake = getattr(status, "brake_status", None)

        if accel is not None and float(accel) == 0.0:
            if not self._accel_zero_triggered:
                print("[actuation_status] accel_status == 0.0")
                print("---")
                print(message_to_yaml(msg))
                ts = self._format_timestamp(
                    msg.header.stamp.sec, msg.header.stamp.nanosec
                )
                self._captured_topics["accel_zero"] = ts
                self._captured_events.append(
                    (
                        self._to_ns(msg.header.stamp.sec, msg.header.stamp.nanosec),
                        "accel_zero",
                        ts,
                    )
                )
                self._accel_zero_triggered = True

        if brake is not None and float(brake) != 0.0:
            if not self._brake_triggered:
                print("[actuation_status] brake_status != 0.0 (brake active)")
                print("---")
                print(message_to_yaml(msg))
                ts = self._format_timestamp(
                    msg.header.stamp.sec, msg.header.stamp.nanosec
                )
                self._captured_topics["brake"] = ts
                self._captured_events.append(
                    (
                        self._to_ns(msg.header.stamp.sec, msg.header.stamp.nanosec),
                        "brake",
                        ts,
                    )
                )
                self._brake_triggered = True

    # 減速し始めたタイミングを出力（longitudinal_velocityで判定）
    def velocity_status_callback(self, msg: VelocityReport):
        if not self._is_running or not self.filters["actuation_status_enable"]:
            return

        try:
            current_velocity = msg.longitudinal_velocity

            if (
                self._prev_velocity is not None
                and current_velocity < self._prev_velocity
            ):
                if not self._decel_started_triggered:
                    print(
                        f"[velocity_status] decelerating start: {self._prev_velocity:.6f} -> {current_velocity:.6f} m/s"
                    )
                    print("---")
                    print(message_to_yaml(msg))
                    ts = self._format_timestamp(
                        msg.header.stamp.sec, msg.header.stamp.nanosec
                    )
                    self._captured_topics["decelerate"] = ts
                    self._captured_events.append(
                        (
                            self._to_ns(msg.header.stamp.sec, msg.header.stamp.nanosec),
                            "decelerate",
                            ts,
                        )
                    )
                    self._decel_started_triggered = True

            self._prev_velocity = current_velocity
        except Exception as e:
            self.get_logger().warn(f"velocity_status parse error: {e}")

    # 自動運転開始（mode: 2）のタイミングを出力
    def operation_mode_callback(self, msg: OperationModeState):
        if not self._is_running or not self.filters["operation_mode_enable"]:
            return

        try:
            if msg.mode == 2:
                if not self._autonomous_mode_triggered:
                    print("[operation_mode/state] autonomous mode started (mode: 2)")
                    print("---")
                    print(message_to_yaml(msg))
                    ts = self._format_timestamp(msg.stamp.sec, msg.stamp.nanosec)
                    self._captured_topics["autonomous_mode"] = ts
                    self._captured_events.append(
                        (
                            self._to_ns(msg.stamp.sec, msg.stamp.nanosec),
                            "autonomous_mode",
                            ts,
                        )
                    )
                    self._autonomous_mode_triggered = True
        except Exception as e:
            self.get_logger().warn(f"operation_mode parse error: {e}")

    def print_captured_summary(self):
        """キャプチャしたトピック情報をまとめて出力（時系列ソート）"""
        print("\n=== Captured Topics Summary (sorted) ===")
        for _, name, ts in sorted(self._captured_events, key=lambda x: x[0]):
            print(f"{name}: {ts}")


def input_thread(node, executor):
    """Enterキー入力を待ち受けるスレッド"""
    print("\n=== Autoware Topic Capture Node ===")
    print("Press Enter to start\n")

    try:
        # 1回目のEnter: ノード開始
        input()
        node._is_running = True
        node.reset_triggers()
        print("=== Node STARTED ===\n")
        print("Press Enter to exit\n")

        # 2回目のEnter: ノード終了
        input()
        print("=== Shutting down... ===")
        executor.shutdown()
    except KeyboardInterrupt:
        print("\n=== Shutting down... ===")
        executor.shutdown()


def main():
    rclpy.init()
    node = AutowareTopicCapture()

    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)

    # 入力待ち受けスレッドを起動
    input_thread_handle = threading.Thread(
        target=input_thread, args=(node, executor), daemon=True
    )
    input_thread_handle.start()

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        # ノード終了前にキャプチャ情報を出力
        node.print_captured_summary()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
