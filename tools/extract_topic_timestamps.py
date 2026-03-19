#!/usr/bin/env python3

"""
YAMLのログから各トピックのタイムスタンプ(ns)を抽出する
"""

from __future__ import annotations

import glob
import os
import re
import sys
from typing import Iterable, List, Tuple

# ブロックを見つける: "[ns/topic] ..." に続いて "---" が来る部分
_BLOCK_PATTERN = re.compile(r"\[(.+?)\][^\n]*\n---\n(.*?)(?=\n\[|$)", re.DOTALL)
# ブロック内のスタンプ(sec, nanosec)を拾う。header: stamp: を含む場合も許容する。
_STAMP_PATTERN = re.compile(
    r"stamp:\s*(?:\n\s*[A-Za-z_]+:.*?)*?\n\s*sec:\s*(\d+)\s*\n\s*nanosec:\s*(\d+)",
    re.DOTALL,
)


def _gather_yaml_paths(args: Iterable[str]) -> List[str]:
    paths: List[str] = []
    for arg in args:
        if os.path.isdir(arg):
            paths.extend(glob.glob(os.path.join(arg, "*.yaml")))
        elif os.path.isfile(arg):
            paths.append(arg)
        else:
            print(f"警告: パスが見つかりません: {arg}")
    return sorted(set(paths))


def _extract_timestamps(content: str) -> List[Tuple[str, int]]:
    """ファイル内容から (topic_ns, timestamp_ns) のリストを抽出する."""
    results: List[Tuple[str, int]] = []
    for block_match in _BLOCK_PATTERN.finditer(content):
        topic_ns = block_match.group(1).strip()
        body = block_match.group(2)
        stamp_match = _STAMP_PATTERN.search(body)
        if not stamp_match:
            continue
        sec = int(stamp_match.group(1))
        nanosec = int(stamp_match.group(2))
        timestamp_ns = sec * 1_000_000_000 + nanosec
        results.append((topic_ns, timestamp_ns))
    return results


def _pick_targets(pairs: List[Tuple[str, int]]) -> dict:
    """対象トピックだけをピックして辞書化する."""
    picked = {}
    for topic_ns, ts in pairs:
        if (
            topic_ns.startswith("operation_mode/state")
            and "autonomous_mode" not in picked
        ):
            picked["autonomous_mode"] = ts
        elif topic_ns.startswith("velocity_status") and "decelerate" not in picked:
            picked["decelerate"] = ts
        elif (
            topic_ns.startswith("obstacle_cruise/virtual_walls")
            and "obstacle_cruise" not in picked
        ):
            picked["obstacle_cruise"] = ts
        elif (
            topic_ns.startswith("obstacle_stop/virtual_walls")
            and "obstacle_stop" not in picked
        ):
            picked["obstacle_stop"] = ts
    return picked


def process_file(yaml_path: str) -> None:
    try:
        with open(yaml_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {yaml_path}")
        return
    except Exception as exc:  # pylint: disable=broad-except
        print(f"エラー: {exc}")
        return

    pairs = _extract_timestamps(content)
    picked = _pick_targets(pairs)

    events: List[Tuple[str, int]] = []
    for name in ("decelerate", "obstacle_cruise", "obstacle_stop"):
        if name not in picked:
            continue
        events.append((name, picked[name]))

    if not events:
        print(f"{yaml_path}: 出力対象のイベントが見つかりませんでした")
        return

    formatted = ", ".join([f"{name}={ts}" for name, ts in events])
    print(f"{yaml_path}: {formatted}")


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "使用方法: python3 extract_topic_timestamps.py <YAMLファイル or ディレクトリ> [...]"
        )
        sys.exit(1)

    yaml_paths = _gather_yaml_paths(sys.argv[1:])
    if not yaml_paths:
        print("エラー: YAMLファイルが見つかりません")
        sys.exit(1)

    for path in yaml_paths:
        process_file(path)


if __name__ == "__main__":
    main()
