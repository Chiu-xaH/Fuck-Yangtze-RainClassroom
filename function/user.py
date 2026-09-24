import requests
from config import host, api, headers


# 获取用户名字 用于写日志
def get_user_name():
    response = requests.get(host + api["user_info"], headers=headers, timeout=15)
    if response.status_code == 200:
        response_data = response.json()
        # 提取 `data` 列表中的第一个元素信息
        if "data" in response_data and response_data["data"]:
            return response_data["data"][0].get("name")
    else:
        return "错误"

