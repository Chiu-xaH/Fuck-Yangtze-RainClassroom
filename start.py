import os
import threading
import time
from datetime import datetime

import requests

from config import filtered_courses
from function.check_in import get_listening_classes_and_sign
from function.listen_window import CHINA_TIME, current_window_end, parse_listen_windows


CHECK_INTERVAL_SECONDS = 300


def main():
    windows = parse_listen_windows(os.getenv("LISTEN_WINDOWS", ""))
    window_end = current_window_end(windows)
    if window_end is None:
        if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch" or not os.getenv("GITHUB_ACTIONS"):
            print("手动单次检查课程", flush=True)
            get_listening_classes_and_sign(filtered_courses)
        else:
            print("当前不在监听窗口，退出", flush=True)
        return

    print("进入配置的监听窗口", flush=True)
    seen_lesson_ids = set()
    window_stop_event = threading.Event()
    listener_threads = []
    try:
        while datetime.now(CHINA_TIME) < window_end:
            try:
                listener_threads.extend(get_listening_classes_and_sign(
                    filtered_courses,
                    seen_lesson_ids=seen_lesson_ids,
                    window_stop_event=window_stop_event,
                    quiet_when_empty=True,
                ) or [])
            except requests.RequestException as error:
                print(f"检查课程暂时失败: {type(error).__name__}", flush=True)

            remaining = (window_end - datetime.now(CHINA_TIME)).total_seconds()
            if remaining <= 0:
                break
            window_stop_event.wait(min(CHECK_INTERVAL_SECONDS, remaining))
    finally:
        window_stop_event.set()
        deadline = time.monotonic() + 5
        for thread in listener_threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        print("监听窗口结束，已停止本次检查", flush=True)

if __name__ == "__main__":
    main()
