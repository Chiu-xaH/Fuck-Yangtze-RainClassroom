# 长江雨课堂定时签到+听课答题
**🌟 雨课堂、荷花、黄河等应该就HOST和API不同吧，可以自己试试，改下API应该就行?**

## 方法1 Github Actions
### 🌟 说明
默认设置为 每周一至周五7:00~22:00，每5min运行一次检查，若发现新的课程则写入log.json；需要定制运行时间，可修改cron表达式,自行学习,注意corn使用0时区时间，应在东八区时间-8

**⚠️ Actions会存在延迟，并不是准时每5min检查一次**

**⚠️ 当进入监听答题状态后，后面的任务会排队，等待监听结束再运行，监听状态可能会半路结束，似乎是什么网络原因，不过有后面排队任务，崩了也能被接替**

解决建议：

1.通过Github Actions API搭配自动化任务，定几个重要的上课时间节点，发送网络请求运行Action 

2.转到第二种食用方法-使用服务器部署自动任务，私有算力100%不会出错

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

6.去Action板块Run,观察运行结果，检查是否通过
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

