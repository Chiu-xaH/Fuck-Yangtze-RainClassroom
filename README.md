# 长江雨课堂定时签到+听课答题
**🌟 雨课堂、荷花、黄河等应该就HOST和API不同吧，可以自己试试，改下API应该就行?**

## 方法1 Github Actions
### 🌟 说明
工作流每 5 分钟尝试启动一次，先按 `LISTEN_WINDOWS` Secret 判断当前是否处于监听时段（北京时间）。时段外直接跳过依赖安装和脚本；时段内会持续运行，每约 5 分钟检查一次课程，发现课程后签到并按 `FILTERED_COURSES` 配置进入监听。到达该时段结束时间后，本轮停止查课并关闭监听连接。同一轮运行不会重复处理同一课堂。

**⚠️ GitHub Actions 的定时触发可能延迟或漏跑，无法保证在指定时刻准时启动，也无法保证严格每 5 分钟检查一次。若本轮错过整个时段，不会补跑。**

**⚠️ 工作流使用并发限制：同一时间最多运行一轮，等待中的定时任务可能被更新的任务替换，不能依赖排队任务接替异常退出的监听。**

解决建议：

1.通过Github Actions API搭配自动化任务，定几个重要的上课时间节点，发送网络请求运行Action 

2.若需要更可控的调度，可转到第二种使用方法，在自己的服务器上部署；仍需自行监控服务和网络状态

**⚠️ 安装依赖较大，约需要75秒后正式开始运行**

**⚠️ 注意 若Cookie过期，Github会发邮件提示运行失败**

### 🚀 开始配置
1.按下面教程拿到SESSIONID，或者自己抓APP的包

2.按图中路径，配置名为SESSION的环境变量，值为SESSIONID的值
![图片1](src/img/Step_1.png)
![图片2](src/img/Step_2.png)

3.继续在设置中，修改选项(为了写入日志)
![图片3](src/img/Step_3.png)


4.再配置两个secret，AI_KEY和ENNCY_KEY，用于搜题答题，获取方式在末尾

5.再配置一个secret，FILTERED_COURSES，用英文逗号隔开，不要有空格，填写需要一直监听答题的课程，为空则代表所有课程都监听

例如：计算机组成原理,数据结构

6.配置名为 `LISTEN_WINDOWS` 的 Secret，填写每周需要自动监听的时间段。例如：

```text
MON=08:00-10:00,14:00-16:00
TUE=09:30-11:30
WED=08:00-09:45
```

使用 `MON` 到 `SUN` 表示周一到周日，时间均为北京时间、24 小时制，格式必须是 `HH:MM-HH:MM`。每天可填多个时段，用英文逗号分隔；不同日期换行，也可用英文分号分隔。每段最长 5 小时，同一天的时段不能重叠，也不能跨午夜；跨午夜请拆成前后两天分别填写。Secret 留空时，定时运行不会进入监听。修改 Secret 后仅影响后续运行，已启动的一轮不会自动更换时段。

7.去 Actions 页面手动点击 `Run workflow` 可检查运行结果。手动触发即使在配置时段外也会单次查课；若在时段内触发，则运行到该时段结束。
![图片4](src/img/Step_4.png)

## 方法2 部署在服务器
### 🌟 说明

**⚠️ 注意 注意设置好运行自动化时的Cookie过期的提醒**

### 🚀 开始配置
1.进入config.py，修改isLocal变量为True

2.填写config.ini

3.安装依赖
```bash
pip install -r requirements.txt
```

4.配置config.py中
```python
filtered_courses=[
        # 默认为空 所有课题监听课程测试
        # 若填写课程名称 则只监听列表里的课，其余课仅签到,建议按自己需求添加
        "计算机组成原理","数据结构"
]
```

5.定时运行start.py(推荐使用宝塔面板定时任务，具体教程自行搜索)
```bash
python start.py
```


## 获取SESSIONID方式

访问 https://changjiang.yuketang.cn/ ,登录后，按F12
![图片1](src/screenShot/1.png)
![图片2](src/screenShot/2.png)
![图片3](src/screenShot/3.png)
![图片4](src/screenShot/4.png)

复制粘贴得到的id到config.txt，并保存即可

## [获取AI_KEY(AI 用于解题或辅助题库搜题规格化答案)](https://api.chatanywhere.org/v1/oauth/free/render)
## [获取ENNCY_KEY(言溪题库 用于题目为空时搜题)](https://tk.enncy.cn/)
