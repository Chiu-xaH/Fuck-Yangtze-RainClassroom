import contextlib
import io
import json
import os
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta
from unittest import mock

import requests


os.environ.setdefault("SESSION", "test-session")


def _install_optional_dependency_stubs():
    ai = types.ModuleType("util.ai")
    ai.request_ai = lambda **_kwargs: ""
    notice = types.ModuleType("util.notice")
    notice.email_notice = lambda **_kwargs: None
    timestamp = types.ModuleType("util.timestamp")
    timestamp.get_date_time = lambda: ""
    timestamp.get_now = lambda: "test-time"
    sys.modules.setdefault("util.ai", ai)
    sys.modules.setdefault("util.notice", notice)
    sys.modules.setdefault("util.timestamp", timestamp)


_install_optional_dependency_stubs()
from function import listening_socket  # noqa: E402


class FakeWebSocket:
    def __init__(self, connected=True):
        self.sock = types.SimpleNamespace(connected=connected)
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed = True
        self.sock.connected = False


class ListeningSocketTests(unittest.TestCase):
    def test_configured_window_checks_repeatedly_then_stops(self):
        import start
        from function.listen_window import CHINA_TIME

        beginning = datetime(2026, 9, 28, 8, 0, tzinfo=CHINA_TIME)
        ending = beginning + timedelta(minutes=10)
        checks = []

        class FakeStopEvent:
            def __init__(self):
                self.stopped = False

            def wait(self, _seconds):
                return self.stopped

            def set(self):
                self.stopped = True

        fake_stop = FakeStopEvent()
        with mock.patch.dict(os.environ, {
            "LISTEN_WINDOWS": "MON=08:00-08:10",
            "GITHUB_ACTIONS": "true",
        }), mock.patch.object(start, "current_window_end", return_value=ending), \
                mock.patch.object(start, "datetime") as fake_datetime, \
                mock.patch.object(start.threading, "Event", return_value=fake_stop), \
                mock.patch.object(start, "get_listening_classes_and_sign",
                                  side_effect=lambda *_args, **_kwargs: checks.append(1) or []):
            fake_datetime.now.side_effect = [
                beginning, beginning, beginning + timedelta(minutes=5),
                beginning + timedelta(minutes=5), ending,
            ]
            start.main()

        self.assertEqual(2, len(checks))
        self.assertTrue(fake_stop.stopped)

    def test_window_end_closes_active_socket(self):
        ready = threading.Event()
        window_stop = threading.Event()
        apps = []

        class FakeWebSocketApp(FakeWebSocket):
            def __init__(self, **_callbacks):
                super().__init__()
                self.closed_event = threading.Event()
                apps.append(self)

            def run_forever(self, **_options):
                ready.set()
                self.closed_event.wait(2)

            def close(self):
                super().close()
                self.closed_event.set()

        with mock.patch.object(listening_socket.websocket, "WebSocketApp", FakeWebSocketApp):
            listener = threading.Thread(
                target=listening_socket.start_socket_ppt,
                args=("ppt", "socket", "lesson", "user"),
                kwargs={"window_stop_event": window_stop},
            )
            listener.start()
            try:
                self.assertTrue(ready.wait(1))
                window_stop.set()
                listener.join(timeout=2)
                self.assertFalse(listener.is_alive())
            finally:
                window_stop.set()
                listener.join(timeout=2)

        self.assertEqual(1, len(apps))
        self.assertTrue(apps[0].closed)

    def test_repeated_checks_do_not_sign_in_same_lesson_twice(self):
        from function import check_in

        lesson = {"courseName": "test course", "lessonId": 123}
        response = types.SimpleNamespace(
            status_code=200,
            headers={"Set-Auth": "test-auth"},
            json=lambda: {"data": {"lessonToken": "test-token", "identityId": 456}},
        )
        seen_lesson_ids = set()
        with mock.patch.object(check_in, "get_listening", return_value={
            "onLessonClassrooms": [lesson]
        }), mock.patch.object(check_in, "check_in_on_listening", return_value=response) as sign_in, \
                mock.patch.object(check_in, "get_user_name", return_value="test user"), \
                mock.patch.object(check_in, "write_log"), \
                mock.patch.object(check_in, "start_all_sockets", return_value=[]):
            for _ in range(2):
                check_in.get_listening_classes_and_sign(
                    [], seen_lesson_ids=seen_lesson_ids, quiet_when_empty=True
                )

        self.assertEqual({123}, seen_lesson_ids)
        self.assertEqual(1, sign_in.call_count)

    def test_ppt_timeout_retries_without_stopping_listener(self):
        ws = FakeWebSocket()
        calls = []

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": {"slides": []}}

        def intermittent_get(**_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise requests.exceptions.Timeout()
            return FakeResponse()

        original_get = listening_socket.requests.get
        listening_socket.requests.get = intermittent_get
        on_message = listening_socket.on_message_connect(
            ppt_jwt="ppt", lesson_id="lesson", identity_id="user",
            socket_jwt="socket", sleep_second=0,
        )
        timeline = json.dumps({"op": "hello", "timeline": [
            {"type": "slide", "pres": "presentation"}
        ]})
        try:
            on_message(ws, timeline)
            on_message.pending_messages.join()
            self.assertEqual("hello", json.loads(ws.sent[-1])["op"])
            on_message(ws, timeline)
            on_message.pending_messages.join()
        finally:
            on_message.stop_processing()
            listening_socket.requests.get = original_get

        self.assertEqual(2, len(calls))
        self.assertEqual("fetchtimeline", json.loads(ws.sent[-1])["op"])

    def test_slow_ppt_fetch_does_not_block_lessonfinished(self):
        started = threading.Event()
        release = threading.Event()
        callback_finished = threading.Event()
        stop_event = threading.Event()
        ws = FakeWebSocket()

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": {"slides": []}}

        def slow_get(**_kwargs):
            started.set()
            release.wait(2)
            return FakeResponse()

        original_get = listening_socket.requests.get
        listening_socket.requests.get = slow_get
        on_message = listening_socket.on_message_connect(
            ppt_jwt="ppt", lesson_id="lesson", identity_id="user",
            socket_jwt="socket", stop_event=stop_event,
        )
        try:
            def receive_timeline():
                on_message(ws, json.dumps({"op": "hello", "timeline": [
                    {"type": "slide", "pres": "presentation"}
                ]}))
                callback_finished.set()

            callback_thread = threading.Thread(target=receive_timeline, daemon=True)
            callback_thread.start()
            self.assertTrue(started.wait(1))
            self.assertTrue(callback_finished.wait(0.2))
            on_message(ws, json.dumps({"op": "lessonfinished"}))
            self.assertTrue(stop_event.is_set())
            self.assertTrue(ws.closed)
        finally:
            release.set()
            callback_thread.join(timeout=1)
            on_message.stop_processing()
            on_message.pending_messages.join()
            listening_socket.requests.get = original_get

    def test_multiple_unlocked_questions_trigger_one_follow_up_poll(self):
        ws = FakeWebSocket()
        answer_calls = []

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": {"slides": [
                    {"coverAlt": "", "problem": {"problemId": problem_id,
                     "problemType": 1, "body": "test", "options": [], "answers": []}}
                    for problem_id in ("q1", "q2")
                ]}}

        original_get = listening_socket.requests.get
        original_answer = listening_socket.answer
        listening_socket.requests.get = lambda **_kwargs: FakeResponse()
        listening_socket.answer = lambda **kwargs: (answer_calls.append(kwargs), True)[1]
        on_message = listening_socket.on_message_connect(
            ppt_jwt="ppt", lesson_id="lesson", identity_id="user",
            socket_jwt="socket", sleep_second=0,
        )
        try:
            on_message(ws, json.dumps({"op": "hello", "timeline": [
                {"type": "slide", "pres": "presentation"}
            ]}))
            on_message(ws, json.dumps({"op": "fetchtimeline", "unlockedproblem": ["q1", "q2"]}))
            on_message.pending_messages.join()
        finally:
            on_message.stop_processing()
            listening_socket.requests.get = original_get
            listening_socket.answer = original_answer

        self.assertEqual(2, len(answer_calls))
        self.assertEqual(2, sum(json.loads(payload)["op"] == "fetchtimeline" for payload in ws.sent))

    def test_answered_question_is_not_reprocessed_after_reconnect(self):
        answered_ids = set()
        seen_ids = set()
        answer_calls = []
        get_calls = []
        output = io.StringIO()

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"data": {"slides": [{
                    "coverAlt": "",
                    "problem": {
                        "problemId": "q1",
                        "problemType": 1,
                        "body": "test question",
                        "options": [],
                        "answers": [],
                    },
                }]}}

        original_get = listening_socket.requests.get
        original_answer = listening_socket.answer
        listening_socket.requests.get = lambda **kwargs: (get_calls.append(kwargs), FakeResponse())[1]
        listening_socket.answer = lambda **kwargs: (answer_calls.append(kwargs), True)[1]
        try:
            with contextlib.redirect_stdout(output):
                for _ in range(2):
                    ws = FakeWebSocket()
                    on_message = listening_socket.on_message_connect(
                        ppt_jwt="ppt",
                        lesson_id="lesson",
                        identity_id="user",
                        socket_jwt="socket",
                        sleep_second=0,
                        answered_problem_ids=answered_ids,
                        seen_problem_ids=seen_ids,
                    )
                    on_message(ws, json.dumps({"op": "hello", "timeline": [
                        {"type": "slide", "pres": "presentation"}
                    ]}))
                    on_message(ws, json.dumps({"op": "fetchtimeline", "unlockedproblem": ["q1"]}))
                    on_message.pending_messages.join()
                    on_message.stop_processing()
        finally:
            listening_socket.requests.get = original_get
            listening_socket.answer = original_answer

        self.assertEqual(2, len(get_calls))
        self.assertEqual(1, len(answer_calls))
        self.assertEqual({"q1"}, answered_ids)
        self.assertEqual(1, output.getvalue().count("发现 1 道新题"))

    def test_notification_is_ignored_without_follow_up_send(self):
        ws = FakeWebSocket()
        on_message = listening_socket.on_message_connect(
            ppt_jwt="ppt", lesson_id="lesson", identity_id="user", socket_jwt="socket"
        )

        on_message(ws, json.dumps({"op": "notification", "notifications": [], "isReply": True}))

        self.assertEqual([], ws.sent)
        on_message.stop_processing()

    def test_lessonfinished_stops_and_does_not_process_more_messages(self):
        ws = FakeWebSocket()
        stop_event = threading.Event()
        on_message = listening_socket.on_message_connect(
            ppt_jwt="ppt",
            lesson_id="lesson",
            identity_id="user",
            socket_jwt="socket",
            stop_event=stop_event,
        )

        on_message(ws, json.dumps({"op": "lessonfinished"}))

        self.assertTrue(stop_event.is_set())
        self.assertTrue(ws.closed)
        self.assertEqual([], ws.sent)
        on_message.stop_processing()

    def test_send_if_connected_skips_closed_socket(self):
        ws = FakeWebSocket(connected=False)

        sent = listening_socket.send_if_connected(ws, {"op": "hello"})

        self.assertFalse(sent)
        self.assertEqual([], ws.sent)

    def test_disconnect_reconnects_with_keepalive_then_stops_after_lessonfinished(self):
        apps = []

        class FakeWebSocketApp(FakeWebSocket):
            def __init__(self, **callbacks):
                super().__init__()
                self.callbacks = callbacks
                self.run_options = None
                apps.append(self)

            def run_forever(self, **options):
                self.run_options = options
                if len(apps) == 2:
                    self.callbacks["on_message"](self, json.dumps({"op": "lessonfinished"}))

        original_app = listening_socket.websocket.WebSocketApp
        original_delay = listening_socket.RECONNECT_DELAY_SECONDS
        listening_socket.websocket.WebSocketApp = FakeWebSocketApp
        listening_socket.RECONNECT_DELAY_SECONDS = 0
        try:
            listening_socket.start_socket_ppt("ppt", "socket", "lesson", "user")
        finally:
            listening_socket.websocket.WebSocketApp = original_app
            listening_socket.RECONNECT_DELAY_SECONDS = original_delay

        self.assertEqual(2, len(apps))
        self.assertEqual(30, apps[0].run_options["ping_interval"])
        self.assertEqual(10, apps[0].run_options["ping_timeout"])
        self.assertTrue(apps[1].closed)


if __name__ == "__main__":
    unittest.main()
