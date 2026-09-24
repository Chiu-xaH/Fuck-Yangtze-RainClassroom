"""Parse weekly listening windows in China Standard Time."""

import os
import re
from datetime import datetime, time, timedelta, timezone


CHINA_TIME = timezone(timedelta(hours=8))
MAX_WINDOW_LENGTH = timedelta(hours=5)
WEEKDAYS = {name: index for index, name in enumerate(
    ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
)}
WINDOW_PATTERN = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


def parse_listen_windows(raw):
    """Accept lines such as MON=08:00-10:00,14:00-16:00."""
    windows = {day: [] for day in range(7)}
    if not raw or not raw.strip():
        return windows

    entries = re.split(r"[;\n]+", raw)
    for entry_number, entry in enumerate(entries, 1):
        entry = entry.strip()
        if not entry:
            continue
        day_text, separator, ranges_text = entry.partition("=")
        day = WEEKDAYS.get(day_text.strip().upper())
        if not separator or day is None or not ranges_text.strip():
            raise ValueError(f"LISTEN_WINDOWS 第 {entry_number} 项的星期或格式无效")

        for range_text in ranges_text.split(","):
            match = WINDOW_PATTERN.fullmatch(range_text.strip())
            if match is None:
                raise ValueError(f"LISTEN_WINDOWS 第 {entry_number} 项的时间格式无效")
            start_hour, start_minute, end_hour, end_minute = map(int, match.groups())
            try:
                start = time(start_hour, start_minute)
                end = time(end_hour, end_minute)
            except ValueError as error:
                raise ValueError(f"LISTEN_WINDOWS 第 {entry_number} 项的时间超出范围") from error
            if end <= start:
                raise ValueError(f"LISTEN_WINDOWS 第 {entry_number} 项须在当天结束；跨午夜请拆成两天")
            if datetime.combine(datetime.min.date(), end) - datetime.combine(
                datetime.min.date(), start
            ) > MAX_WINDOW_LENGTH:
                raise ValueError(f"LISTEN_WINDOWS 第 {entry_number} 项不能超过 5 小时")
            windows[day].append((start, end))

    for day_ranges in windows.values():
        day_ranges.sort()
        for previous, current in zip(day_ranges, day_ranges[1:]):
            if current[0] < previous[1]:
                raise ValueError("LISTEN_WINDOWS 中存在重叠时间段")
    return windows


def current_window_end(windows, now=None):
    """Return the current window end in CST, or None when outside all windows."""
    local_now = (now or datetime.now(CHINA_TIME)).astimezone(CHINA_TIME)
    current_time = local_now.time().replace(tzinfo=None)
    for start, end in windows[local_now.weekday()]:
        if start <= current_time < end:
            return datetime.combine(local_now.date(), end, CHINA_TIME)
    return None


def main():
    windows = parse_listen_windows(os.getenv("LISTEN_WINDOWS", ""))
    active = current_window_end(windows) is not None
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"active={'true' if active else 'false'}\n")
    print("当前处于监听窗口" if active else "当前不在监听窗口")


if __name__ == "__main__":
    main()
