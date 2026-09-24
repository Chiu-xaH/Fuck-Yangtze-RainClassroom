import json
import os
import sys
import threading
import types
import unittest


os.environ.setdefault("SESSION", "test-session")


def _install_optional_dependency_stubs():
    ai = types.ModuleType("util.ai")
    ai.request_ai = lambda **_kwargs: ""
    notice = types.ModuleType("util.notice")
    notice.email_notice = lambda **_kwargs: None
    timestamp = types.ModuleType("util.timestamp")
    timestamp.get_date_time = lambda: ""
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
    def test_answered_question_is_not_reprocessed_after_reconnect(self):
        answered_ids = set()
        answer_calls = []
        get_calls = []

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
            for _ in range(2):
                ws = FakeWebSocket()
                on_message = listening_socket.on_message_connect(
                    ppt_jwt="ppt",
                    lesson_id="lesson",
                    identity_id="user",
                    socket_jwt="socket",
                    sleep_second=0,
                    answered_problem_ids=answered_ids,
                )
                on_message(ws, json.dumps({"op": "hello", "timeline": [
                    {"type": "slide", "pres": "presentation"}
                ]}))
                on_message(ws, json.dumps({"op": "fetchtimeline", "unlockedproblem": ["q1"]}))
        finally:
            listening_socket.requests.get = original_get
            listening_socket.answer = original_answer

        self.assertEqual(2, len(get_calls))
        self.assertEqual(1, len(answer_calls))
        self.assertEqual({"q1"}, answered_ids)

    def test_notification_is_ignored_without_follow_up_send(self):
        ws = FakeWebSocket()
        on_message = listening_socket.on_message_connect(
            ppt_jwt="ppt", lesson_id="lesson", identity_id="user", socket_jwt="socket"
        )

        on_message(ws, json.dumps({"op": "notification", "notifications": [], "isReply": True}))

        self.assertEqual([], ws.sent)

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
