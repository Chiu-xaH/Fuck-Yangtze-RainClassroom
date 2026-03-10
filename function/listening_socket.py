import threading
import time

import requests
import websocket
import json
from config import host, api, headers, question_type
from util.notice import email_notice
from util.ai import request_ai
from util.timestamp import get_date_time


def on_message_connect(ppt_jwt, lesson_id, identity_id, socket_jwt, sleep_second=10):
    problem_list = dict()

    def on_message(ws, message):
        # 下课 结束监听
        if "lessonfinished" in message:
            print("下课了 关闭连接")
            ws.close()  # 关闭 WebSocket 连接
        # 定时监听当前进度
        msg_json = json.loads(message)
        action = msg_json.get("op")
        if action == "fetchtimeline":
            # 检查返回timeline的最后一个（最新的时间）是否为problem，是则回答问题
            # time_lines = msg_json.get("timeline", [])
            # 过滤 time_lines["type"]!="problem"移除列表
            time_lines = msg_json.get("unlockedproblem",[])
            # 最新的题目
            if len(time_lines) == 0:
                # 没题可答，继续获取PPT内容，看看是否老师换了新的PPT文件
                print("目前无题目，休息片刻后重新获取PPT")
                time.sleep(sleep_second)
                auth_payload = {
                    "op": "hello",
                    "userid": identity_id,
                    "role": "student",
                    "auth": socket_jwt,
                    "lessonid": lesson_id
                }
                ws.send(json.dumps(auth_payload))
            else:
                for q_id in time_lines :
                    # 根据id进行检索已有的列表problem_list成员为dict,key["id"]为id
                    problem = problem_list.get(q_id)
                    if problem is not None:
                        answer(
                            problem_id=q_id,
                            problem_type=problem["type"],
                            problem_content=problem["content"],
                            options=problem["options"],
                            jwt=ppt_jwt,
                            img_url=problem["img_url"]
                        )
                        # 移除回答完的问题
                        if q_id in problem_list:
                            del problem_list[q_id]
                    # 答题/检查完成后再次发送检查 直到(下课)关闭socket通道
                    ws.send(json.dumps({
                        "op": "fetchtimeline",
                        "lessonid": str(lesson_id),
                        "msgid": 1
                    }))
            # 睡一会，别频率过头了被封
            time.sleep(sleep_second)
        else:
            # 首次获取PPT内容，进而保存所有题目
            # 解析出pres_id
            ppt_ids = set()
            if "timeline" in message:
                time_lines = list(json.loads(message)["timeline"])
                # 每一item中type=slide代表每一张PPT，拿到pres后，请求get_ppt接口拿到PPT具体内容，然后进行检测是否有problem
                for item in time_lines:
                    # 是PPT
                    if item["type"] == "slide":
                        ppt_ids.add(item["pres"])
            else:
                print("错误", message)
            # 开始获取PPT
            new_headers = headers
            new_headers["Authorization"] = "Bearer " + ppt_jwt
            new_headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0")

            for pres_id in ppt_ids:
                url = host + api["get_ppt"].format(pres_id)

                response = requests.get(headers=new_headers, url=url)
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
                            if len(answered) == 0: # 回答完的问题不入队
                                # 保存
                                save_dict = {
                                    "type": question["problemType"],
                                    "content": question["body"],
                                    "options": options,
                                    "img_url": ppt["coverAlt"]
                                }
                                print("保存题目", save_dict)
                                problem_list[question["problemId"]] = save_dict
                else:
                    print("错误", response.status_code, response.content)
            # 开始监听 定时发送
            # 这是发送一次
            print("题目保存成功，切换至监听状态")
            ws.send(json.dumps({
                "op": "fetchtimeline",
                "lessonid": str(lesson_id),
                "msgid": 1
            }))
    return on_message


def on_error(ws, error):
    print("出错:", error)


def on_close(ws, close_status_code, close_msg):
    return


def on_open_connet(jwt, lesson_id, identity_id):
    def on_open(ws):
        auth_payload = {
            "op": "hello",
            "userid": identity_id,
            "role": "student",
            "auth": jwt,
            "lessonid": lesson_id
        }
        ws.send(json.dumps(auth_payload))

    return on_open


# 监听上课
def start_socket_ppt(ppt_jwt, socket_jwt, lesson_id, identity_id):
    ws = websocket.WebSocketApp(
        url=api["websocket"],
        on_open=on_open_connet(lesson_id=lesson_id, identity_id=identity_id, jwt=socket_jwt),
        on_message=on_message_connect(ppt_jwt=ppt_jwt, lesson_id=lesson_id, identity_id=identity_id,
                                      socket_jwt=socket_jwt),
        on_error=on_error,
        on_close=on_close,
    )

    ws.run_forever()


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
    else:
        email_notice(content="答题失败，请手动前往雨课堂", subject="答题失败")
        print("答题失败")
        msg = response.json()["msg"]
        if msg == "LESSON_END":
            print("题目已经结束")
        else:
            print(msg)
