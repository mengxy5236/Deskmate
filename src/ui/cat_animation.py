"""
小猫动画模块：加载并播放小猫的各种动画状态

支持的状态：
  - idle: 待机（循环播放）
  - sleeping: 睡觉（循环播放）
  - walkingleft: 向左走（播放一次）
  - walkingright: 向右走（播放一次）
  - angry: 生气（播放一次）
  - zzz: 睡觉时的 Zzz 动画（循环播放）
"""
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap


class CatAnimation:
    """小猫动画管理器"""
    
    # 动画状态配置
    ANIMATIONS = {
        'idle': {
            'frames': ['idle1.png', 'idle2.png', 'idle3.png', 'idle4.png'],
            'loop': True,
            'interval': 200,  # 毫秒
        },
        'sleeping': {
            'frames': ['sleeping1.png', 'sleeping2.png', 'sleeping3.png', 'sleeping4.png',
                      'sleeping5.png', 'sleeping6.png'],
            'loop': False,
            'interval': 300,
            'next_state': 'zzz',  # 卧倒后进入 ZZZ 状态
        },
        'walkingleft': {
            'frames': ['walkingleft1.png', 'walkingleft2.png', 'walkingleft3.png', 'walkingleft4.png'],
            'loop': False,
            'interval': 150,
        },
        'walkingright': {
            'frames': ['walkingright1.png', 'walkingright2.png', 'walkingright3.png', 'walkingright4.png'],
            'loop': False,
            'interval': 150,
        },
        'angry': {
            'frames': ['angry.png'],
            'loop': True,
            'interval': 500,
        },
        'zzz': {
            'frames': ['zzz1.png', 'zzz2.png', 'zzz3.png', 'zzz4.png'],
            'loop': True,
            'interval': 400,
        },
    }
    
    def __init__(self, size: int = 64):
        self._size = size
        self._assets_path = Path(__file__).parent.parent / "assets"
        self._current_state = 'idle'
        self._current_frame = 0
        self._frames: dict[str, list[QPixmap]] = {}
        self._timer = QTimer()
        self._timer.timeout.connect(self._next_frame)
        
        # 加载所有动画帧
        self._load_all_frames()
        
        # 开始播放待机动画
        self.play('idle')
    
    def _load_all_frames(self):
        """预加载所有动画帧"""
        for state, config in self.ANIMATIONS.items():
            self._frames[state] = []
            for frame_name in config['frames']:
                frame_path = self._assets_path / frame_name
                if frame_path.exists():
                    pixmap = QPixmap(str(frame_path))
                    # 缩放到指定大小
                    scaled = pixmap.scaled(
                        self._size, self._size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self._frames[state].append(scaled)
                else:
                    print(f"警告: 找不到帧图片 {frame_path}")
    
    def _next_frame(self):
        """切换到下一帧"""
        config = self.ANIMATIONS[self._current_state]
        self._current_frame += 1
        
        if self._current_frame >= len(self._frames[self._current_state]):
            if config['loop']:
                self._current_frame = 0
            else:
                # 非循环动画结束后，检查是否有下一个状态
                next_state = config.get('next_state')
                if next_state:
                    self.play(next_state)
                else:
                    # 没有下一个状态则回到待机状态
                    self._current_frame = len(self._frames[self._current_state]) - 1
                    self.play('idle')
    
    def play(self, state: str):
        """播放指定状态的动画"""
        if state not in self.ANIMATIONS:
            print(f"未知动画状态: {state}")
            return
        
        # 停止当前动画
        self._timer.stop()
        
        # 切换到新状态
        self._current_state = state
        self._current_frame = 0
        
        # 启动定时器
        interval = self.ANIMATIONS[state]['interval']
        self._timer.start(interval)
    
    def get_current_frame(self) -> QPixmap:
        """获取当前帧"""
        frames = self._frames.get(self._current_state, [])
        if frames and self._current_frame < len(frames):
            return frames[self._current_frame]
        # 如果没有加载到帧，返回空 pixmap
        return QPixmap(self._size, self._size)
    
    def stop(self):
        """停止动画"""
        self._timer.stop()
    
    def start(self):
        """开始/恢复动画"""
        if not self._timer.isActive():
            interval = self.ANIMATIONS[self._current_state]['interval']
            self._timer.start(interval)
    
    @property
    def current_state(self) -> str:
        """获取当前动画状态"""
        return self._current_state
    
    @property
    def size(self) -> int:
        """获取动画尺寸"""
        return self._size
