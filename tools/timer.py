# -*- coding: utf-8 -*-
"""
高精度计时器模块 - 用于统计 AI 推理各步骤耗时

Usage:
    from tools.timer import timer
    
    # 启用/禁用
    timer.enable()
    timer.disable()
    
    # 记录耗时
    with timer.record("condyle_seg.inference"):
        model.predict(...)
    
    # 获取报告
    timer.print_report()
    timer.save_report("timer_report.txt")
"""

import time
import logging
from contextlib import contextmanager
from typing import Dict, Tuple, Optional
from collections import OrderedDict

logger = logging.getLogger(__name__)


class Timer:
    """
    高精度计时器 - 单例模式
    
    用于统计 Pipeline 各模块的 Pre/Inference/Post 耗时。
    
    Attributes:
        enabled (bool): 全局开关，控制是否启用计时
        current_context (Dict[str, float]): 当前请求的各步骤耗时
            - Key: 步骤名（如 "condyle_seg.pre", "condyle_seg.inference"）
            - Value: 耗时（秒）
        global_stats (Dict[str, Tuple[float, int]]): 历史累计数据
            - Key: 步骤名
            - Value: (total_time, count) 用于计算平均值
        _start_time (float): Pipeline 开始时间
    """
    
    _instance: Optional['Timer'] = None
    
    def __new__(cls) -> 'Timer':
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化计时器"""
        if self._initialized:
            return
        
        self._enabled: bool = True
        self._current_context: Dict[str, float] = OrderedDict()
        self._global_stats: Dict[str, Tuple[float, int]] = {}
        self._start_time: Optional[float] = None
        self._report_file: str = "timer_report.txt"
        self._console_output: bool = True
        self._initialized = True
        
        logger.info("Timer initialized (singleton)")
    
    # ==================== 开关控制 ====================
    
    def enable(self) -> None:
        """启用计时器"""
        self._enabled = True
        logger.info("Timer enabled")
    
    def disable(self) -> None:
        """禁用计时器"""
        self._enabled = False
        logger.info("Timer disabled")
    
    def is_enabled(self) -> bool:
        """检查计时器是否启用"""
        return self._enabled
    
    # ==================== 核心计时 ====================
    
    def reset(self) -> None:
        """
        重置当前上下文，开始新一轮统计。
        在每次 Pipeline.run() 开始时调用。
        """
        self._current_context = OrderedDict()
        self._start_time = time.perf_counter() if self._enabled else None
        logger.debug("Timer context reset")
    
    @contextmanager
    def record(self, name: str):
        """
        上下文管理器，用于包裹代码块进行计时。
        
        Args:
            name: 步骤名称，建议格式为 "module.stage"
                  如 "condyle_seg.pre", "condyle_seg.inference", "teeth_seg.post"
        
        Usage:
            with timer.record("condyle_seg.inference"):
                result = model.predict(image)
        """
        if not self._enabled:
            yield
            return
        
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._current_context[name] = elapsed
            
            # 更新全局统计
            if name in self._global_stats:
                total, count = self._global_stats[name]
                self._global_stats[name] = (total + elapsed, count + 1)
            else:
                self._global_stats[name] = (elapsed, 1)
            
            logger.debug(f"[Timer] {name}: {elapsed:.4f}s")
    
    # ==================== 数据访问 ====================
    
    def get_current_duration(self, name: str) -> float:
        """获取指定步骤的当前耗时"""
        return self._current_context.get(name, 0.0)
    
    def get_total_duration(self) -> float:
        """获取当前请求的总耗时"""
        if self._start_time is None:
            return sum(self._current_context.values())
        return time.perf_counter() - self._start_time
    
    def get_average(self, name: str) -> float:
        """获取指定步骤的历史平均耗时"""
        if name not in self._global_stats:
            return 0.0
        total, count = self._global_stats[name]
        return total / count if count > 0 else 0.0
    
    def get_batch_count(self) -> int:
        """获取已统计的批次数量"""
        if not self._global_stats:
            return 0
        # 取任意一个步骤的 count 作为批次数
        _, count = next(iter(self._global_stats.values()))
        return count
    
    # ==================== 报告生成 ====================
    
    def get_report_string(self) -> str:
        """
        生成当前上下文的格式化报告。
        
        Returns:
            str: 格式化的计时报告
        """
        if not self._enabled:
            return "Timer is disabled."
        
        if not self._current_context:
            return "No timing data recorded."
        
        lines = ["=" * 40]
        lines.append("       Timer Report (Current)")
        lines.append("=" * 40)
        
        # 按模块分组
        modules = self._group_by_module(self._current_context)
        
        for module_name, stages in modules.items():
            lines.append(f"\n[{module_name}]")
            for stage, duration in stages.items():
                stage_label = self._format_stage_label(stage)
                lines.append(f"  {stage_label:<16}: {duration:.4f}s")
        
        # 总耗时
        total = self.get_total_duration()
        lines.append("\n" + "-" * 40)
        lines.append(f"Total Duration: {total:.4f}s")
        lines.append("=" * 40)
        
        return "\n".join(lines)
    
    def get_average_report_string(self) -> str:
        """
        生成历史平均耗时报告。
        
        Returns:
            str: 格式化的平均耗时报告
        """
        if not self._enabled:
            return "Timer is disabled."
        
        if not self._global_stats:
            return "No historical timing data."
        
        batch_count = self.get_batch_count()
        
        lines = ["=" * 40]
        lines.append(f"  Timer Report (Average of {batch_count} runs)")
        lines.append("=" * 40)
        
        # 计算平均值
        averages = {
            name: total / count 
            for name, (total, count) in self._global_stats.items()
        }
        
        # 按模块分组
        modules = self._group_by_module(averages)
        
        for module_name, stages in modules.items():
            lines.append(f"\n[{module_name}]")
            for stage, avg_duration in stages.items():
                stage_label = self._format_stage_label(stage)
                lines.append(f"  {stage_label:<16}: {avg_duration:.4f}s")
        
        # 平均总耗时
        total_avg = sum(averages.values())
        lines.append("\n" + "-" * 40)
        lines.append(f"Avg Total Duration: {total_avg:.4f}s")
        lines.append("=" * 40)
        
        return "\n".join(lines)
    
    def _group_by_module(self, data: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        """按模块名分组数据"""
        modules: Dict[str, Dict[str, float]] = OrderedDict()
        
        for name, value in data.items():
            parts = name.split(".")
            if len(parts) >= 2:
                module_name = parts[0]
                stage = ".".join(parts[1:])
            else:
                module_name = "Other"
                stage = name
            
            if module_name not in modules:
                modules[module_name] = OrderedDict()
            modules[module_name][stage] = value
        
        return modules
    
    def _format_stage_label(self, stage: str) -> str:
        """格式化阶段标签"""
        label_map = {
            "pre": "Pre-processing",
            "inference": "Inference",
            "post": "Post-processing",
            "analysis": "Analysis",
            "measurement": "Measurement",
            "generation": "Generation",
        }
        return label_map.get(stage, stage.capitalize())
    
    # ==================== 输出 ====================
    
    def print_report(self) -> None:
        """打印报告到控制台"""
        if self._console_output:
            print(self.get_report_string())
    
    def save_report(self, filepath: Optional[str] = None) -> None:
        """
        将报告写入文件（覆盖模式）
        
        Args:
            filepath: 目标文件路径，如果为 None 则使用配置中的路径
        """
        if not self._enabled:
            logger.warning("Timer is disabled, skip saving report.")
            return
        
        if filepath is None:
            filepath = self._report_file
        
        try:
            report = self.get_report_string()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Timer report saved to: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save timer report: {e}")
    
    def clear_global_stats(self) -> None:
        """清空历史累计数据"""
        self._global_stats = {}
        logger.info("Global statistics cleared")


# 模块级单例导出
timer = Timer()


def configure_from_config(config: dict) -> None:
    """
    从配置字典加载 Timer 设置
    
    Args:
        config: 配置字典，应包含 'timer' 键
                格式：
                {
                    'timer': {
                        'enabled': True,
                        'report_file': 'timer_report.txt',
                        'console_output': True
                    }
                }
    """
    timer_config = config.get('timer', {})
    
    if not isinstance(timer_config, dict):
        logger.warning("Invalid timer config, using defaults")
        return
    
    # 设置启用/禁用
    if timer_config.get('enabled', True):
        timer.enable()
    else:
        timer.disable()
    
    # 保存报告文件路径（供后续使用）
    timer._report_file = timer_config.get('report_file', 'timer_report.txt')
    timer._console_output = timer_config.get('console_output', True)
    
    logger.info(f"Timer configured: enabled={timer.is_enabled()}, report_file={timer._report_file}")


def configure_from_yaml(config_path: str = "config.yaml") -> None:
    """
    从 YAML 配置文件加载 Timer 设置
    
    Args:
        config_path: 配置文件路径
    """
    try:
        import yaml
        from pathlib import Path
        
        config_file = Path(config_path)
        if not config_file.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if config:
            configure_from_config(config)
        else:
            logger.warning(f"Config file is empty: {config_path}")
    
    except Exception as e:
        logger.warning(f"Failed to load timer config from {config_path}: {e}")

