# -*- coding: utf-8 -*-
"""
牙期检测 Pipeline
基于牙齿分割结果，判断牙列类型（混合牙列 vs 恒牙列）
"""

from pipelines.base_pipeline import BasePipeline
from pipelines.pano.modules.teeth_seg import TeethSegmentationModule
from PIL import Image
import logging

logger = logging.getLogger(__name__)

# 乳牙 FDI 编码（国际牙科联盟标准）
DECIDUOUS_TEETH_FDI = [
    "51", "52", "53", "54", "55",  # 上颌右侧乳牙
    "61", "62", "63", "64", "65",  # 上颌左侧乳牙
    "71", "72", "73", "74", "75",  # 下颌左侧乳牙
    "81", "82", "83", "84", "85"   # 下颌右侧乳牙
]


class DentalAgePipeline(BasePipeline):
    """
    牙期检测 Pipeline
    
    功能：
        - 基于牙齿分割模块检测牙齿
        - 判断是否包含乳牙（FDI 编码 5x, 6x, 7x, 8x）
        - 返回牙列类型（Mixed: 混合牙列, Permanent: 恒牙列）
    
    复用：
        - 复用全景片的 TeethSegmentationModule
        - 配置可以共享 panoramic 的 teeth_seg 配置
    """
    
    def __init__(self, *, modules: dict = None):
        """
        初始化牙期检测 Pipeline
        
        Args:
            modules: 模块配置字典，需包含 'teeth_seg' 配置
        """
        super().__init__()
        self.pipeline_type = "dental_age_stage"
        
        # 复用全景片的牙齿分割模块配置
        teeth_config = modules.get('teeth_seg', {}) if modules else {}
        self.teeth_seg = TeethSegmentationModule(**teeth_config)
        
        logger.info(f"DentalAgePipeline initialized with teeth_seg config: {teeth_config}")
    
    def run(self, image_path: str, **kwargs) -> dict:
        """
        执行牙期检测
        
        Args:
            image_path: 全景片图像路径
            **kwargs: 额外参数（暂未使用）
        
        Returns:
            dict: 包含牙期检测结果
                {
                    "dentalAgeStage": "Mixed" | "Permanent",
                    "teethAnalysis": {
                        "totalDetected": int,
                        "deciduousCount": int,
                        "permanentCount": int,
                        "deciduousTeeth": List[str],
                        "permanentTeeth": List[str]
                    }
                }
        
        工作流程:
            1. 加载图像
            2. 调用牙齿分割模块
            3. 解析检测到的牙齿 FDI 编码
            4. 判断是否包含乳牙
            5. 返回牙列类型和详细分析
        """
        logger.info(f"Running dental age stage detection for: {image_path}")
        
        # 1. 加载图像
        img = Image.open(image_path).convert('RGB')
        
        # 2. 执行牙齿分割
        raw_results = self.teeth_seg.predict(img)
        class_names = raw_results.get('class_names', [])
        
        logger.info(f"Detected {len(class_names)} teeth: {class_names}")
        
        # 3. 分析牙齿类型（乳牙 vs 恒牙）
        deciduous_teeth = []
        permanent_teeth = []
        
        for cls_name in class_names:
            # 牙齿类名格式：'tooth-11', 'tooth-52', etc.
            fdi = cls_name.split('-')[-1]  # 提取 FDI 编码
            
            if fdi in DECIDUOUS_TEETH_FDI:
                deciduous_teeth.append(fdi)
            else:
                permanent_teeth.append(fdi)
        
        # 4. 判断牙列类型
        has_deciduous = len(deciduous_teeth) > 0
        dental_age_stage = "Mixed" if has_deciduous else "Permanent"
        
        logger.info(
            f"Dental age stage: {dental_age_stage} "
            f"(deciduous: {len(deciduous_teeth)}, permanent: {len(permanent_teeth)})"
        )
        
        # 5. 构造返回结果
        return {
            "dentalAgeStage": dental_age_stage,
            "teethAnalysis": {
                "totalDetected": len(class_names),
                "deciduousCount": len(deciduous_teeth),
                "permanentCount": len(permanent_teeth),
                "deciduousTeeth": sorted(deciduous_teeth),
                "permanentTeeth": sorted(permanent_teeth)
            }
        }

