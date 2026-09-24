import queue
import threading

import requests
import websocket
import json
from config import host, api, headers, question_type
from util.notice import email_notice
from util.ai import request_ai
from util.timestamp import get_date_time

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10
RECONNECT_DELAY_SECONDS = 5


def send_if_connected(ws, payload):
    """Send a WebSocket payload only while the underlying connection is open."""
    sock = getattr(ws, "sock", None)
    if not getattr(sock, "connected", False):
        print("WebSocket 未连接，跳过发送", flush=True)
        return False

    try:
        ws.send(json.dumps(payload))
        return True
    except (OSError, websocket.WebSocketException) as error:
        print(f"WebSocket 发送失败: {error!r}", flush=True)
        return False


def on_message_connect(ppt_jwt, lesson_id, identity_id, socket_jwt, sleep_second=10,
                       stop_event=None, answered_problem_ids=None,
                       processing_problem_ids=None, seen_problem_ids=None,
                       problem_state_lock=None):
    problem_list = dict()
    if answered_problem_ids is None:
        answered_problem_ids = set()
    if processing_problem_ids is None:
        processing_problem_ids = set()
    if seen_problem_ids is None:
        seen_problem_ids = set()
    if problem_state_lock is None:
        problem_state_lock = threading.Lock()
    processor_stop = threading.Event()
    messages = queue.Queue()
    reported_errors = set()

    def stopped():
        return processor_stop.is_set() or (stop_event is not None and stop_event.is_set())

    def process_message(ws, msg_json):
        if stopped():
            return
        action = msg_json.get("op")
        if action == "fetchtimeline":
            # 检查返回timeline的最后一个（最新的时间）是否为problem，是则回答问题
            # time_lines = msg_json.get("timeline", [])
            # 过滤 time_lines["type"]!="problem"移除列表
            time_lines = msg_json.get("unlockedproblem",[])
            # 最新的题目
            if len(time_lines) == 0:
                # 没题可答，继续获取PPT内容，看看是否老师换了新的PPT文件
                if processor_stop.wait(sleep_second * 2) or stopped():
                    return
                auth_payload = {
                    "op": "hello",
                    "userid": identity_id,
                    "role": "student",
                    "auth": socket_jwt,
                    "lessonid": lesson_id
                }
                send_if_connected(ws, auth_payload)
            else:
                for q_id in time_lines:
                    if stopped():
                        return
                    # 根据id进行检索已有的列表problem_list成员为dict,key["id"]为id
                    problem = problem_list.get(q_id)
                    if problem is not None:
                        with problem_state_lock:
                            should_answer = (q_id not in answered_problem_ids
                                             and q_id not in processing_problem_ids)
                            if should_answer:
                                processing_problem_ids.add(q_id)
                        if should_answer:
                            try:
                                answered = answer(
                                    problem_id=q_id,
                                    problem_type=problem["type"],
                                    problem_content=problem["content"],
                                    options=problem["options"],
                                    jwt=ppt_jwt,
                                    img_url=problem["img_url"]
                                )
                                if answered:
                                    with problem_state_lock:
                                        answered_problem_ids.add(q_id)
                            finally:
                                with problem_state_lock:
                                    processing_problem_ids.discard(q_id)
                        # 移除回答完的问题
                        if q_id in problem_list:
                            del problem_list[q_id]
                # 整批处理后只发一次查询，避免多题时请求成倍增长
                if processor_stop.wait(sleep_second) or stopped():
                    return
                send_if_connected(ws, {
                    "op": "fetchtimeline",
                    "lessonid": str(lesson_id),
                    "msgid": 1
                })
        else:
            # 首次获取PPT内容，进而保存所有题目
            # 解析出pres_id
            ppt_ids = set()
            if "timeline" in msg_json:
                time_lines = list(msg_json["timeline"])
                # 每一item中type=slide代表每一张PPT，拿到pres后，请求get_ppt接口拿到PPT具体内容，然后进行检测是否有problem
                for item in time_lines:
                    # 是PPT
                    if item["type"] == "slide":
                        ppt_ids.add(item["pres"])
            else:
                return
            # 开始获取PPT
            new_headers = headers.copy()
            new_headers["Authorization"] = "Bearer " + ppt_jwt
            new_headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0")

            new_problem_count = 0
            for pres_id in ppt_ids:
                if stopped():
                    return
                url = host + api["get_ppt"].format(pres_id)

                response = requests.get(headers=new_headers, url=url, timeout=15)
                if response.status_code == 200:
                    ppt_pages = response.json()["data"]["slides"]
                    for ppt in ppt_pages:
                        # 有答题
                        if "problem" in ppt:
                            # print(ppt)
                            # 先保存所有题目，供索引，然后监听socket，对应的问题发送的瞬间进行answer
                            question = ppt["problem"]
                            options = None
                            q_type = question["problemType"]
                            if q_type == 1 or q_type == 2 or q_type == 3:
                                options = question["options"]

                            answered = list(ppt["problem"]["answers"])
                            with problem_state_lock:
                                should_save = (question["problemId"] not in answered_problem_ids
                                               and question["problemId"] not in processing_problem_ids)
                            if len(answered) == 0 and should_save:
                                # 保存
                                save_dict = {
                                    "type": question["problemType"],
                                    "content": question["body"],
                                    "options": options,
                                    "img_url": ppt["coverAlt"]
                                }
                                with problem_state_lock:
                                    if question["problemId"] not in seen_problem_ids:
                                        seen_problem_ids.add(question["problemId"])
                                        new_problem_count += 1
                                problem_list[question["problemId"]] = save_dict
                else:
                    print(f"获取 PPT 失败，HTTP {response.status_code}", flush=True)
            # 开始监听 定时发送
            # 这是发送一次
            if new_problem_count:
                print(f"发现 {new_problem_count} 道新题，继续监听", flush=True)
            if stopped():
                return
            send_if_connected(ws, {
                "op": "fetchtimeline",
                "lessonid": str(lesson_id),
                "msgid": 1
            })

    def process_queued_messages():
        while True:
            item = messages.get()
            try:
                if item is None:
                    return
                if not stopped():
                    process_message(*item)
                    reported_errors.clear()
            except Exception as error:
                error_name = type(error).__name__
                if error_name not in reported_errors:
                    print(f"监听消息处理失败: {error_name}，稍后重新获取课堂内容", flush=True)
                    reported_errors.add(error_name)
                if not stopped() and not processor_stop.wait(sleep_second * 2):
                    ws, _ = item
                    send_if_connected(ws, {
                        "op": "hello",
                        "userid": identity_id,
                        "role": "student",
                        "auth": socket_jwt,
                        "lessonid": lesson_id,
                    })
            finally:
                messages.task_done()

    # 保持 WebSocket 的接收回调空闲，以便及时读取心跳回应。
    worker = threading.Thread(target=process_queued_messages, daemon=True)
    worker.start()

    def on_message(ws, message):
        if "lessonfinished" in message:
            print("下课了，停止监听", flush=True)
            if stop_event is not None:
                stop_event.set()
            processor_stop.set()
            ws.close()
            return
        try:
            msg_json = json.loads(message)
        except json.JSONDecodeError:
            print("收到无法解析的 WebSocket 消息", flush=True)
            return
        if not isinstance(msg_json, dict):
            print("收到非对象 WebSocket 消息", flush=True)
            return
        if msg_json.get("op") == "notification" or stopped():
            return
        messages.put((ws, msg_json))

    def stop_processing():
        processor_stop.set()
        messages.put(None)

    on_message.stop_processing = stop_processing
    on_message.pending_messages = messages
    return on_message


def on_error(ws, error):
    print(f"WebSocket 错误: {error!r}", flush=True)


def on_close(ws, close_status_code, close_msg):
    print(
        f"WebSocket 已关闭，code={close_status_code!r}, reason={close_msg!r}",
        flush=True,
    )


def on_open_connet(jwt, lesson_id, identity_id):
    def on_open(ws):
        auth_payload = {
            "op": "hello",
            "userid": identity_id,
            "role": "student",
            "auth": jwt,
            "lessonid": lesson_id
        }
        send_if_connected(ws, auth_payload)

    return on_open


# 监听上课
def start_socket_ppt(ppt_jwt, socket_jwt, lesson_id, identity_id):
    stop_event = threading.Event()
    reconnect_attempt = 0
    answered_problem_ids = set()
    processing_problem_ids = set()
    seen_problem_ids = set()
    problem_state_lock = threading.Lock()

    while not stop_event.is_set():
        on_message = on_message_connect(
            ppt_jwt=ppt_jwt,
            lesson_id=lesson_id,
            identity_id=identity_id,
            socket_jwt=socket_jwt,
            stop_event=stop_event,
            answered_problem_ids=answered_problem_ids,
            processing_problem_ids=processing_problem_ids,
            seen_problem_ids=seen_problem_ids,
            problem_state_lock=problem_state_lock,
        )
        ws = websocket.WebSocketApp(
            url=api["websocket"],
            on_open=on_open_connet(lesson_id=lesson_id, identity_id=identity_id, jwt=socket_jwt),
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        try:
            ws.run_forever(
                ping_interval=PING_INTERVAL_SECONDS,
                ping_timeout=PING_TIMEOUT_SECONDS,
            )
        finally:
            on_message.stop_processing()

        if stop_event.is_set():
            break

        reconnect_attempt += 1
        print(
            f"WebSocket 连接中断，{RECONNECT_DELAY_SECONDS} 秒后重连（第 {reconnect_attempt} 次）",
            flush=True,
        )
        stop_event.wait(RECONNECT_DELAY_SECONDS)


# 多线程 多个上课同时监听
def start_all_sockets(on_lesson_list):
    threads = []

    for item in on_lesson_list:
        t = threading.Thread(
            target=start_socket_ppt,
            kwargs={
                "ppt_jwt": item["ppt_jwt"],
                "socket_jwt": item["socket_jwt"],
                "lesson_id": item["lesson_id"],
                "identity_id": item["identity_id"]
            }
        )
        t.start()
        threads.append(t)

    # for t in threads:
    #     t.join()  # 等待所有线程结束（如果需要）


# 答题
def answer(problem_id, problem_type, jwt, problem_content, options,img_url):
    print(question_type[problem_type], problem_content, options,img_url)

    post_json = {
        "problemId": problem_id,
        "problemType": problem_type,
        "dt": get_date_time(),
        "result": request_ai(type=question_type[problem_type], problem=problem_content, options=options,img_url=img_url)
    }

    new_headers = headers
    new_headers["Authorization"] = "Bearer " + jwt
    new_headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0")

    response = requests.post(url=host + api["answer"], json=post_json, headers=new_headers)

    if response.status_code == 200:
        print("答题成功")
        return True
    else:
        email_notice(content="答题失败，请手动前往雨课堂", subject="答题失败")
        print("答题失败")
        msg = response.json()["msg"]
        if msg == "LESSON_END":
            print("题目已经结束")
        else:
            print(msg)
        return False
