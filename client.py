import cv2
import mss
import mss.base
import mss.screenshot
import numpy as np
import time
import socket
import uuid
import pyautogui
import threading
import argparse
import pystray
from PIL import Image


# 截屏对象转换成OpenCV对象
def screenshot2Mat(screenshot: mss.screenshot.ScreenShot):
    return np.array(screenshot)


# 打印动作帧数
def printFrameRate(original_func):
    def wrapper(cls, *args, **kwrd):
        begin = time.time()
        result = original_func(cls, *args, **kwrd)
        end = time.time()
        # 打印帧数
        print(1 / (end - begin))
        return result

    return wrapper


# 将OpenCV对象转换为字节流
def mat2Bytes(mat: cv2.typing.MatLike):
    _, img_encoded = cv2.imencode(".png", mat)
    return img_encoded.tobytes()


def string_to_bytes(string, length):
    # 编码字符串为字节数组
    encoded_string = string.encode("utf-8")
    # 如果字符串长度超过指定长度，进行截断
    if len(encoded_string) > length:
        encoded_string = encoded_string[:length]
    # 如果字符串长度不足，进行填充
    elif len(encoded_string) < length:
        encoded_string += b"\x00" * (length - len(encoded_string))
    return encoded_string


def bytes_to_string(byte_array):
    # 解码字节数组为字符串
    string = byte_array.decode("utf-8")
    return string


def connect_retry(seconds):
    for i in range(seconds):
        print("\r连接失败，重试倒计时{:^5}秒".format(5 - i), end="")
        time.sleep(1)
    print("\r\033[K", end="")


class ScreenCatcher:
    # 上一帧图
    prevframe: cv2.typing.MatLike = None
    id: uuid.UUID = None
    refreshtime: float = None
    scale: float = 1.0
    connect_lock = threading.Lock()
    exit_event = threading.Event()
    sendframe_event = threading.Event()

    def __init__(self) -> None:
        self.initMenu()
        self.initCurser()
        self.initArgs()
        self.initMonitor()
        self.connectServer()

    # 初始化小菜单
    def initMenu(self):
        print("初始化小菜单")
        try:
            icon = Image.open(r"computer.png")
        except:
            icon = Image.open(r"./_internal/icon/computer.png")
        app_name = "nf_desktop_monitor"
        menu = (
            pystray.MenuItem("退出应用", action=self.exitMenu),
            # pystray.MenuItem('通道建立', action=Command.buildSocket),
            # pystray.MenuItem('开启心跳检测', action=Command.startHeartCheck),
            # pystray.MenuItem('开启屏幕推流', action=Command.beginCapture),
        )
        app = pystray.Icon(app_name, icon, app_name, menu)

        def init(menu):
            menu.visible = True

        def start():
            app.run(setup=init)

        threading.Thread(target=start).start()

    def exitMenu(self, menu):
        menu.stop()
        self.exit_event.set()
        self.cmdRecvSock.close()
        # self.cmdSendSock.close()
        self.frameSendSock.close()

    def connectServer(self):
        # 尝试获取锁，如果获取不到则跳过
        if self.connect_lock.acquire(blocking=False) and not self.exit_event.is_set():
            try:
                self.login()
                self.initFrameSendSock()
                # self.initCommandSendSock()
                self.initCommandReceiveSock()
            finally:
                self.connect_lock.release()

    def initArgs(self):
        # 创建解析器对象
        parser = argparse.ArgumentParser(description="description")
        # 添加具名参数
        parser.add_argument(
            "-s", "--server", type=str, required=False, help="set server's IP address"
        )
        # 解析命令行参数
        self.args = parser.parse_args()

    # 连接图像收集服务器
    def initFrameSendSock(self):
        # 远程服务器的地址和端口
        server_address = ((self.args.server or "127.0.0.1"), 9000)
        # 创建TCP套接字
        self.frameSendSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print("连接图像收集服务器...", end="")
            self.frameSendSock.connect(server_address)
            print("已连接")
        except Exception as err:
            print(err)
            if not self.exit_event.is_set():
                connect_retry(5)
                self.initFrameSendSock()

    # 连接指令收集服务器
    def initCommandSendSock(self):
        # 远程服务器的地址和端口
        server_address = ((self.args.server or "127.0.0.1"), 9100)
        # 创建TCP套接字
        self.cmdSendSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print("连接指令收集服务器...", end="")
            self.cmdSendSock.connect(server_address)
            print("已连接")
        except Exception as err:
            print(err)
            if not self.exit_event.is_set():
                connect_retry(5)
                self.initCommandSendSock()

    # 连接指令分发服务器
    def initCommandReceiveSock(self):
        # 远程服务器的地址和端口
        server_address = ((self.args.server or "127.0.0.1"), 9101)
        # 创建TCP套接字
        self.cmdRecvSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print("连接指令分发服务器...", end="")
            self.cmdRecvSock.connect(server_address)
            self.cmdRecvSock.sendall(self.id.bytes)
            self.cmdRecvSock.recv(1)
            print("已连接")
        except Exception as err:
            print(err)
            if not self.exit_event.is_set():
                connect_retry(5)
                self.initCommandReceiveSock()

    # 获取截屏区域
    def initMonitor(self):
        # 获取屏幕尺寸
        with mss.mss() as sct:
            monitor = sct.monitors[0]
            screen_width = monitor["width"]
            screen_height = monitor["height"]
        # 设置捕获区域（这里设置为整个屏幕）
        self.monitor = {
            "top": 0,
            "left": 0,
            "width": screen_width,
            "height": screen_height,
        }

    # 获取登录令牌
    def login(self):
        # 远程服务器的地址和端口
        server_address = ((self.args.server or "127.0.0.1"), 8888)
        # 创建TCP套接字
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print("连接用户认证服务器...", end="")
            sock.connect(server_address)
            print("已连接....")
            print("登录账号....")
            sock.sendall(string_to_bytes("user1", 10))
            sock.sendall(string_to_bytes("password", 20))
            uuid_bytes = sock.recv(16)
            self.id = uuid.UUID(bytes=uuid_bytes)
            print("登录令牌已获取", self.id)
            sock.close()
        except Exception as err:
            print(err)
            if not self.exit_event.is_set():
                connect_retry(5)
                self.login()

    # 截屏动作
    # @printFrameRate
    def sendFrame(self, sct: mss.base.MSSBase):
        if not self.sendframe_event.is_set():
            time.sleep(1)
            return
        # 获取屏幕截图
        frame = sct.grab(self.monitor)
        frame_mat = screenshot2Mat(frame)
        self.addCurser(frame_mat)
        nowtime = time.time()
        if (
            self.prevframe is None
            or self.refreshtime is None
            or (nowtime - self.refreshtime) > 1
        ):
            header, desc, body = self.refresh(frame_mat)
            self.refreshtime = nowtime
        else:
            header, desc, body = self.update(frame_mat)
        if header is None:
            return
        # 发送图像大小、尺寸、位置
        self.frameSendSock.sendall(header)
        self.frameSendSock.sendall(desc)
        # 发送图像数据
        self.frameSendSock.sendall(body)
        self.prevframe = cv2.cvtColor(frame_mat, cv2.COLOR_BGR2GRAY)

    # 生成刷新帧数据
    def refresh(self, mat: cv2.typing.MatLike):
        # print("发送刷新帧")
        body = mat2Bytes(mat)
        size = len(body)
        height, width, channel = mat.shape
        x = y = 0
        header = self.id.bytes + int(0).to_bytes(4, byteorder="big")
        desc = (
            size.to_bytes(4, byteorder="big")
            + height.to_bytes(4, byteorder="big")
            + width.to_bytes(4, byteorder="big")
            + x.to_bytes(4, byteorder="big")
            + y.to_bytes(4, byteorder="big")
        )
        return header, desc, body

    # 生成更新帧数据
    def update(self, mat: cv2.typing.MatLike):
        # 转换图片格式
        curframe = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
        # 计算两帧之间的差异
        diff = cv2.absdiff(curframe, self.prevframe)
        # 应用阈值处理
        _, thresholded_diff = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        # 找到变化区域的轮廓
        contours, _ = cv2.findContours(
            thresholded_diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if len(contours) == 0:
            return None, None, None
        # 切片过多则执行刷新动作
        if len(contours) > 3000:
            print("切片数量过多：", len(contours))
            return self.refresh(mat)
        # 发送变化区域图像数据
        body = b""
        header = b""
        desc = b""
        # 添加切片数量
        header = self.id.bytes + len(contours).to_bytes(4, byteorder="big")
        slice_nbytes = 0
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            # 变化区域图像切片
            slice = mat[y : y + h, x : x + w]
            # 将切片图像转换为字节流
            _, slice_encoded = cv2.imencode(".png", slice)
            slice_bytes = slice_encoded.tobytes()
            # 发送图像大小、尺寸、位置
            size = len(slice_bytes)
            slice_info = (
                size.to_bytes(4, byteorder="big")
                + h.to_bytes(4, byteorder="big")
                + w.to_bytes(4, byteorder="big")
                + x.to_bytes(4, byteorder="big")
                + y.to_bytes(4, byteorder="big")
            )
            desc += slice_info
            body += slice_bytes
            slice_nbytes += slice.nbytes
        # 切片过大则执行刷新动作
        size_rate = slice_nbytes / mat.nbytes * 100
        if size_rate > 90:
            print("切片尺寸过大：", size_rate, "%")
            return self.refresh(mat)
        return header, desc, body

    # 初始化鼠标指针图像
    def initCurser(self):
        try:
            with open(r"curser_point.png", "rb") as file:
                # 读取PNG图标（带透明通道）
                self.curser = cv2.imdecode(
                    np.frombuffer(file.read(), np.uint8), cv2.IMREAD_UNCHANGED
                )
        except:
            with open(r"./_internal/icon/curser_point.png", "rb") as file:
                # 读取PNG图标（带透明通道）
                self.curser = cv2.imdecode(
                    np.frombuffer(file.read(), np.uint8), cv2.IMREAD_UNCHANGED
                )

    # 添加鼠标指针
    def addCurser(self, frame):
        # 获取图标的尺寸
        h, w = self.curser.shape[:2]
        # 创建一个全透明的图像作为蒙版
        overlay_mask = self.curser[..., 3:] / 255.0
        overlay_img = self.curser[..., :3]
        # 获取鼠标位置
        x, y = pyautogui.position()
        # 定位放置图标的位置
        y1, y2 = y, y + h
        x1, x2 = x, x + w
        # 确保坐标在图像边界内
        if x1 < 0 or y1 < 0 or x2 > frame.shape[1] or y2 > frame.shape[0]:
            return
        # 提取背景区域
        bg_region = frame[y1:y2, x1:x2, :3]
        # 进行加权合成
        combined = (1.0 - overlay_mask) * bg_region + overlay_mask * overlay_img
        # 将合成后的图像放回原背景图像
        frame[y1:y2, x1:x2, :3] = combined

    def recvCommand(self):
        header_bytes = self.cmdRecvSock.recv(24)
        id_bytes = header_bytes[0:16]
        print("\r正在受到来自{0}的控制\t".format(uuid.UUID(bytes=id_bytes)), end="")
        # 接收指令类型
        type_bytes = header_bytes[16:20]
        # 接收指令大小
        size_bytes = header_bytes[20:24]
        cmd_type = int.from_bytes(type_bytes, byteorder="big")
        body_size = int.from_bytes(size_bytes, byteorder="big")
        # 接收指令
        body_bytes = self.cmdRecvSock.recv(body_size)
        if cmd_type == 1:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.moveTo(x, y, duration=0)
        elif cmd_type == 2:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.mouseDown(x, y, button="left")
        elif cmd_type == 3:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.mouseDown(x, y, button="right")
        elif cmd_type == 4:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.mouseDown(x, y, button="middle")
        elif cmd_type == 5:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.mouseUp(x, y, button="left")
        elif cmd_type == 6:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.mouseUp(x, y, button="right")
        elif cmd_type == 7:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.mouseUp(x, y, button="middle")
        elif cmd_type == 8:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.doubleClick(x, y, button="left")
        elif cmd_type == 9:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.doubleClick(x, y, button="right")
        elif cmd_type == 10:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.doubleClick(x, y, button="middle")
        elif cmd_type == 11:
            x = int.from_bytes(body_bytes[:4], byteorder="big")
            y = int.from_bytes(body_bytes[4:8], byteorder="big")
            pyautogui.scroll(5, x, y)
        elif cmd_type == 20:
            print("开始推送图像")
            self.sendframe_event.set()
        elif cmd_type == 21:
            print("停止推送图像")
            self.sendframe_event.clear()


if __name__ == "__main__":
    catcher = ScreenCatcher()
    pyautogui.PAUSE = 0

    def sendFrame():
        with mss.mss() as sct:
            while not catcher.exit_event.is_set():
                try:
                    catcher.sendFrame(sct)
                except Exception as err:
                    print(err)
                    catcher.connectServer()
                    time.sleep(3)

    def recvCmd():
        while not catcher.exit_event.is_set():
            try:
                catcher.recvCommand()
            except Exception as err:
                print(err)
                catcher.connectServer()
                time.sleep(3)

    thread1 = threading.Thread(target=sendFrame)
    thread2 = threading.Thread(target=recvCmd)
    thread1.start()
    thread2.start()
    thread1.join()
    thread2.join()
