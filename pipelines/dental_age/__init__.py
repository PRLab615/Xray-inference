# -*- coding: utf-8 -*-
"""
牙期检测 Pipeline
基于全景片牙齿分割结果，判断是否为混合牙列期
"""

from pipelines.dental_age.dental_age_pipeline import DentalAgePipeline

__all__ = ['DentalAgePipeline']

