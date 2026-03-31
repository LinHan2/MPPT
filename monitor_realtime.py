#!/usr/bin/env python3
"""
LibreSolar MPPT 实时数据可视化工具
监控 /dev/ttyUSB0 串口数据并实时绘制曲线
"""

import serial
import json
import matplotlib
matplotlib.use('TkAgg')  # 使用Tk后端避免OpenGL错误
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from datetime import datetime
from collections import deque
import time
import sys

# 配置
SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200
MAX_POINTS = 300  # 最多显示300个数据点 (约5分钟@1Hz)

# 数据存储 (使用deque实现固定长度的滚动缓冲区)
data_buffer = {
    'time': deque(maxlen=MAX_POINTS),  # 改为相对时间(秒)
    'bat_v': deque(maxlen=MAX_POINTS),
    'bat_a': deque(maxlen=MAX_POINTS),
    'solar_v': deque(maxlen=MAX_POINTS),
    'solar_a': deque(maxlen=MAX_POINTS),
    'load_a': deque(maxlen=MAX_POINTS),
    'load_bus_v': deque(maxlen=MAX_POINTS),
    'bat_power': deque(maxlen=MAX_POINTS),
    'solar_power': deque(maxlen=MAX_POINTS),
    'soc': deque(maxlen=MAX_POINTS),
    'chg_state': deque(maxlen=MAX_POINTS),
    'dcdc_state': deque(maxlen=MAX_POINTS),
    'load_info': deque(maxlen=MAX_POINTS),
    'load_err_flags': deque(maxlen=MAX_POINTS),
}

# 记录开始时间
start_time = time.time()

# 充电状态映射,1表示快速充电，2表示涓流充电，0表示空闲，3表示补充充电
CHG_STATE_NAMES = {
    0: 'IDLE',
    1: 'BULK',
    2: 'TOPPING',
    3: 'TRICKLE'
}

DCDC_STATE_NAMES = {
    0: 'OFF',
    1: 'MPPT',
    2: 'CC_HS',
    3: 'CC_LS',
    4: 'CV_HS',
    5: 'CV_LS'
}

LOAD_INFO_NAMES = {
    1:  'NORMAL',
    0:  'SHEDDING',
    -1: 'LVD',
    -2: 'OVERVOLT',
    -3: 'OVERCURR',
    -4: 'SHORT',
    -5: 'TEMP_HIGH',
}

class MPPTMonitor:
    def __init__(self, port, baudrate):
        try:
            self.ser = serial.Serial(port, baudrate, timeout=1)
            print(f"✅ 成功连接到 {port} @ {baudrate} baud")
        except serial.SerialException as e:
            print(f"❌ 无法打开串口 {port}: {e}")
            print(f"💡 提示: sudo chmod 666 {port}")
            sys.exit(1)

        # 创建图形界面
        self.fig, self.axes = plt.subplots(3, 2, figsize=(14, 10))
        self.fig.suptitle('LibreSolar MPPT 实时监控', fontsize=16, fontweight='bold')

        # 设置中文字体支持 (可选)
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
        plt.rcParams['axes.unicode_minus'] = False

        self.setup_plots()

    def setup_plots(self):
        """设置各个子图"""
        # 子图1: 电池电压 + LoadBus电压
        self.ax_bat_v = self.axes[0, 0]
        self.line_bat_v, = self.ax_bat_v.plot([], [], 'b-', linewidth=2, label='Battery Voltage')
        self.line_load_bus_v, = self.ax_bat_v.plot([], [], 'r--', linewidth=1.5, label='LoadBus Voltage')
        self.ax_bat_v.set_ylabel('Voltage (V)', fontsize=10)
        self.ax_bat_v.set_title('Battery / Load Bus Voltage', fontweight='bold')
        self.ax_bat_v.grid(True, alpha=0.3)
        self.ax_bat_v.legend(loc='upper right')

        # 子图2: 太阳能板电压
        self.ax_solar_v = self.axes[0, 1]
        self.line_solar_v, = self.ax_solar_v.plot([], [], 'orange', linewidth=2, label='Solar Voltage')
        self.ax_solar_v.set_ylabel('Voltage (V)', fontsize=10)
        self.ax_solar_v.set_title('Solar Panel Voltage', fontweight='bold')
        self.ax_solar_v.grid(True, alpha=0.3)
        self.ax_solar_v.legend(loc='upper right')

        # 子图3: 电流 (电池 + 太阳能 + 负载)
        self.ax_current = self.axes[1, 0]
        self.line_bat_a, = self.ax_current.plot([], [], 'b-', linewidth=2, label='Battery')
        self.line_solar_a, = self.ax_current.plot([], [], 'orange', linewidth=2, label='Solar')
        self.line_load_a, = self.ax_current.plot([], [], 'r-', linewidth=2, label='Load')
        self.ax_current.set_ylabel('Current (A)', fontsize=10)
        self.ax_current.set_title('Current Flow', fontweight='bold')
        self.ax_current.grid(True, alpha=0.3)
        self.ax_current.legend(loc='upper right')
        self.ax_current.axhline(y=0, color='k', linestyle='--', alpha=0.3)

        # 子图4: 功率
        self.ax_power = self.axes[1, 1]
        self.line_bat_p, = self.ax_power.plot([], [], 'b-', linewidth=2, label='Battery Power')
        self.line_solar_p, = self.ax_power.plot([], [], 'orange', linewidth=2, label='Solar Power')
        self.ax_power.set_ylabel('Power (W)', fontsize=10)
        self.ax_power.set_title('Power Flow', fontweight='bold')
        self.ax_power.grid(True, alpha=0.3)
        self.ax_power.legend(loc='upper right')
        self.ax_power.axhline(y=0, color='k', linestyle='--', alpha=0.3)

        # 子图5: SOC (State of Charge)
        self.ax_soc = self.axes[2, 0]
        self.line_soc, = self.ax_soc.plot([], [], 'g-', linewidth=2, label='SOC')
        self.ax_soc.set_ylabel('SOC (%)', fontsize=10)
        self.ax_soc.set_title('Battery State of Charge', fontweight='bold')
        self.ax_soc.set_ylim(0, 105)
        self.ax_soc.grid(True, alpha=0.3)
        self.ax_soc.legend(loc='upper right')

        # 子图6: 状态文本显示
        self.ax_status = self.axes[2, 1]
        self.ax_status.axis('off')
        self.status_text = self.ax_status.text(0.05, 0.95, '', transform=self.ax_status.transAxes,
                                               fontsize=11, verticalalignment='top',
                                               family='monospace',
                                               bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        # 调整布局
        plt.tight_layout(rect=[0, 0, 1, 0.96])

    def parse_thingset_line(self, line):
        """解析ThingSet JSON数据"""
        try:
            line = line.strip()
            if not line:
                return None

            # 移除开头的 '# ' 标记
            if line.startswith('#'):
                line = line.lstrip('#').strip()

            # 跳过非JSON行
            if not line.startswith('{'):
                return None

            data = json.loads(line)

            # 提取需要的数据
            result = {
                'timestamp': time.time() - start_time,  # 相对时间(秒)
                'bat_v': data.get('Bat_V', 0),
                'bat_a': data.get('Bat_A', 0),
                'solar_v': data.get('Solar_V', 0),
                'solar_a': data.get('Solar_A', 0),
                'load_a': data.get('Load_A', 0),
                'load_bus_v': data.get('LoadBus_V', 0),
                'load_info': data.get('LoadInfo', 0),
                'load_lvd_trip': data.get('LoadLvdTrip_V', 0),
                'load_ov_trip': data.get('LoadOvTrip_V', 0),
                'load_err_flags': data.get('LoadErrFlags', 0),
                'soc': data.get('SOC_pct', 0),
                'chg_state': data.get('ChgState', 0),
                'dcdc_state': data.get('DCDCState', 0),
                'uptime': data.get('Uptime_s', 0),
                'error_flags': data.get('ErrorFlags', 0),
            }

            # 计算功率
            result['bat_power'] = result['bat_v'] * result['bat_a']
            result['solar_power'] = result['solar_v'] * result['solar_a']

            return result

        except json.JSONDecodeError:
            return None
        except Exception as e:
            print(f"解析错误: {e}")
            return None

    def read_serial_data(self):
        """从串口读取一行数据"""
        try:
            if self.ser.in_waiting > 0:
                line = self.ser.readline().decode('utf-8', errors='ignore')
                return self.parse_thingset_line(line)
        except Exception as e:
            print(f"读取串口错误: {e}")
        return None

    def update_data_buffer(self, data):
        """更新数据缓冲区"""
        if data is None:
            return

        data_buffer['time'].append(data['timestamp'])
        data_buffer['bat_v'].append(data['bat_v'])
        data_buffer['bat_a'].append(data['bat_a'])
        data_buffer['solar_v'].append(data['solar_v'])
        data_buffer['solar_a'].append(data['solar_a'])
        data_buffer['load_a'].append(data['load_a'])
        data_buffer['load_bus_v'].append(data['load_bus_v'])
        data_buffer['bat_power'].append(data['bat_power'])
        data_buffer['solar_power'].append(data['solar_power'])
        data_buffer['soc'].append(data['soc'])
        data_buffer['chg_state'].append(data['chg_state'])
        data_buffer['dcdc_state'].append(data['dcdc_state'])
        data_buffer['load_info'].append(data['load_info'])
        data_buffer['load_err_flags'].append(data['load_err_flags'])

        # 更新状态文本
        chg_name = CHG_STATE_NAMES.get(data['chg_state'], 'UNKNOWN')
        dcdc_name = DCDC_STATE_NAMES.get(data['dcdc_state'], 'UNKNOWN')
        load_info_name = LOAD_INFO_NAMES.get(data['load_info'], f"ERR({data['load_info']})")
        load_ok = data['load_info'] == 1
        load_status_icon = '✅' if load_ok else '❌'

        status_str = f"""
╔══════════════════════════════════╗
║       MPPT 实时状态              ║
╠══════════════════════════════════╣
║ Uptime:        {data['uptime']:6d} s      ║
║ Charge State:  {chg_name:7s}        ║
║ DCDC State:    {dcdc_name:7s}        ║
║                                  ║
║ Battery:   {data['bat_v']:5.2f}V  {data['bat_a']:6.2f}A ║
║ Solar:     {data['solar_v']:5.2f}V  {data['solar_a']:6.2f}A ║
║ Load:               {data['load_a']:6.2f}A ║
║ LoadBus:   {data['load_bus_v']:5.2f}V           ║
║                                  ║
║ Bat Power:        {data['bat_power']:7.2f} W  ║
║ Solar Power:      {data['solar_power']:7.2f} W  ║
║                                  ║
║ SOC:              {data['soc']:6.1f} %   ║
║ Errors:           0x{data['error_flags']:04X}     ║
╠══════════════════════════════════╣
║ Load: {load_status_icon} {load_info_name:10s}          ║
║ LVD Trip:      {data['load_lvd_trip']:5.2f} V        ║
║ OV  Trip:      {data['load_ov_trip']:5.2f} V        ║
║ Load ErrFlags: 0x{data['load_err_flags']:04X}        ║
╚══════════════════════════════════╝
        """
        self.status_text.set_text(status_str)

    def update_plot(self, frame):
        """动画更新函数"""
        # 读取新数据
        data = self.read_serial_data()
        if data:
            self.update_data_buffer(data)
            current_time = datetime.now().strftime('%H:%M:%S')
            load_info_name = LOAD_INFO_NAMES.get(data['load_info'], f"ERR({data['load_info']})")
            print(f"[{current_time}] "
                  f"Bat: {data['bat_v']:.2f}V {data['bat_a']:+.2f}A | "
                  f"Solar: {data['solar_v']:.2f}V {data['solar_a']:.2f}A | "
                  f"SOC: {data['soc']:.0f}% | "
                  f"Load: {load_info_name} | "
                  f"State: {CHG_STATE_NAMES.get(data['chg_state'], '?')}")

        # 如果没有数据,不更新图表
        if len(data_buffer['time']) == 0:
            return []

        times = list(data_buffer['time'])

        # 更新所有曲线
        self.line_bat_v.set_data(times, list(data_buffer['bat_v']))
        self.line_load_bus_v.set_data(times, list(data_buffer['load_bus_v']))
        self.line_solar_v.set_data(times, list(data_buffer['solar_v']))

        self.line_bat_a.set_data(times, list(data_buffer['bat_a']))
        self.line_solar_a.set_data(times, list(data_buffer['solar_a']))
        self.line_load_a.set_data(times, list(data_buffer['load_a']))

        self.line_bat_p.set_data(times, list(data_buffer['bat_power']))
        self.line_solar_p.set_data(times, list(data_buffer['solar_power']))

        self.line_soc.set_data(times, list(data_buffer['soc']))

        # 自动调整X轴范围
        if len(times) > 1:
            x_min, x_max = times[0], times[-1]
            for ax in [self.ax_bat_v, self.ax_solar_v, self.ax_current,
                      self.ax_power, self.ax_soc]:
                ax.set_xlim(x_min, x_max)
                ax.relim()
                ax.autoscale_view(scalex=False, scaley=True)

        # 设置X轴标签
        for ax in [self.ax_bat_v, self.ax_solar_v, self.ax_current,
                  self.ax_power, self.ax_soc]:
            if ax == self.ax_soc or ax == self.ax_power:
                ax.set_xlabel('Time (s)', fontsize=9)

        return []

    def run(self):
        """启动实时监控"""
        print("\n🚀 开始实时监控...")
        print(f"📊 显示最近 {MAX_POINTS} 个数据点")
        print("💡 关闭窗口或按 Ctrl+C 退出\n")

        # 创建动画 (每秒更新10次,但串口数据通常是1Hz)
        ani = animation.FuncAnimation(
            self.fig,
            self.update_plot,
            interval=100,  # 100ms更新一次
            blit=False,
            cache_frame_data=False
        )

        try:
            plt.show()
        except KeyboardInterrupt:
            print("\n\n👋 监控已停止")
        finally:
            self.ser.close()
            print("🔌 串口已关闭")

def main():
    print("=" * 60)
    print("  LibreSolar MPPT 实时数据可视化工具")
    print("=" * 60)
    print(f"串口: {SERIAL_PORT}")
    print(f"波特率: {BAUD_RATE}")
    print()

    monitor = MPPTMonitor(SERIAL_PORT, BAUD_RATE)
    monitor.run()

if __name__ == '__main__':
    main()
