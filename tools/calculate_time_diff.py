#!/usr/bin/env python3

import glob
import os
import re
import sys


def extract_timestamps(yaml_file: str) -> dict:
    """YAMLファイルからタイムスタンプを抽出する"""
    timestamps = {}

    with open(yaml_file, "r") as f:
        content = f.read()

    # [operation_mode/state] autonomous_modeを探す
    autonomous_mode_match = re.search(
        r"\[operation_mode/state\].*?\nstamp:\s*\n\s*sec:\s*(\d+)\s*\n\s*nanosec:\s*(\d+)",
        content,
        re.DOTALL,
    )
    if autonomous_mode_match:
        sec = int(autonomous_mode_match.group(1))
        nanosec = int(autonomous_mode_match.group(2))
        timestamps["autonomous_mode"] = sec * 1_000_000_000 + nanosec

    # [velocity_status] decelerateを探す
    decelerate_match = re.search(
        r"\[velocity_status\].*?\nheader:\s*\n\s*stamp:\s*\n\s*sec:\s*(\d+)\s*\n\s*nanosec:\s*(\d+)",
        content,
        re.DOTALL,
    )
    if decelerate_match:
        sec = int(decelerate_match.group(1))
        nanosec = int(decelerate_match.group(2))
        timestamps["decelerate"] = sec * 1_000_000_000 + nanosec

    # [obstacle_stop/virtual_walls] obstacle_stopを探す
    obstacle_stop_match = re.search(
        r"\[obstacle_stop/virtual_walls\].*?\nheader:\s*\n\s*stamp:\s*\n\s*sec:\s*(\d+)\s*\n\s*nanosec:\s*(\d+)",
        content,
        re.DOTALL,
    )
    if obstacle_stop_match:
        sec = int(obstacle_stop_match.group(1))
        nanosec = int(obstacle_stop_match.group(2))
        timestamps["obstacle_stop"] = sec * 1_000_000_000 + nanosec

    # [obstacle_cruise/virtual_walls] obstacle_cruiseを探す
    obstacle_cruise_match = re.search(
        r"\[obstacle_cruise/virtual_walls\].*?\nheader:\s*\n\s*stamp:\s*\n\s*sec:\s*(\d+)\s*\n\s*nanosec:\s*(\d+)",
        content,
        re.DOTALL,
    )
    if obstacle_cruise_match:
        sec = int(obstacle_cruise_match.group(1))
        nanosec = int(obstacle_cruise_match.group(2))
        timestamps["obstacle_cruise"] = sec * 1_000_000_000 + nanosec

    return timestamps


def process_file(yaml_file: str) -> None:
    """ファイルを処理して時間差を計算して表示する"""
    # ファイルが存在するか確認
    try:
        timestamps = extract_timestamps(yaml_file)
    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {yaml_file}")
        return
    except Exception as e:
        print(f"エラー: {e}")
        return

    # 必須タイムスタンプが抽出されたか確認
    if "autonomous_mode" not in timestamps or "decelerate" not in timestamps:
        print(
            f"警告: {yaml_file} 必要なタイムスタンプ(autonomous_mode, decelerate)が抽出できませんでした"
        )
        return

    # ナノ秒を秒に変換（1秒 = 10^9 ナノ秒）
    NS_TO_S = 1e9

    autonomous_mode_ns = timestamps["autonomous_mode"]

    # イベントのリストを作成（タイムスタンプ順にソート）
    events = []

    # decelerateは必須
    decelerate_ns = timestamps["decelerate"]
    decelerate_diff_s = (decelerate_ns - autonomous_mode_ns) / NS_TO_S
    events.append(("decelerate", decelerate_ns, decelerate_diff_s))

    # obstacle_stopがある場合
    if "obstacle_stop" in timestamps:
        obstacle_stop_ns = timestamps["obstacle_stop"]
        obstacle_stop_diff_s = (obstacle_stop_ns - autonomous_mode_ns) / NS_TO_S
        events.append(("obstacle_stop", obstacle_stop_ns, obstacle_stop_diff_s))

    # obstacle_cruiseがある場合
    if "obstacle_cruise" in timestamps:
        obstacle_cruise_ns = timestamps["obstacle_cruise"]
        obstacle_cruise_diff_s = (obstacle_cruise_ns - autonomous_mode_ns) / NS_TO_S
        events.append(("obstacle_cruise", obstacle_cruise_ns, obstacle_cruise_diff_s))

    # タイムスタンプでソート
    events.sort(key=lambda x: x[1])

    # 出力
    output = f"{yaml_file}: "
    output += ", ".join([f"{name}={diff:.9f}s" for name, _, diff in events])

    print(output)


def main():
    if len(sys.argv) < 2:
        print(
            "使用方法: python3 calculate_time_diff.py <YAMLファイルパス or ディレクトリパス>"
        )
        sys.exit(1)

    yaml_files = []

    # 複数のファイル/ディレクトリを処理
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            yaml_files.extend(glob.glob(os.path.join(arg, "*.yaml")))
        elif os.path.isfile(arg):
            yaml_files.append(arg)
        else:
            print(f"警告: パスが見つかりません: {arg}")

    if not yaml_files:
        print("エラー: YAMLファイルが見つかりません")
        sys.exit(1)

    yaml_files.sort()

    print("=== 時刻差の計算 ===")
    for yaml_file in yaml_files:
        process_file(yaml_file)


if __name__ == "__main__":
    main()
