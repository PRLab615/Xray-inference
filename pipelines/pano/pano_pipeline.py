# -*- coding: utf-8 -*-
"""
全景片推理管道 (最终生产版)
集成模块：
1. 髁突 (Condyle): V2 左右分离
2. 上颌窦 (Sinus): V2 左右分离 + 轮廓修复
3. 神经管 (Neural): 独立分割模块
4. 牙齿/种植体/属性/牙周: 完整保留
"""

from pipelines.base_pipeline import BasePipeline
from pipelines.pano.utils import pano_report_utils
from tools.timer import timer
import logging
from datetime import datetime
import cv2
import numpy as np

# ---------------------------------------------------------
# 1. 导入各个模块的 Predictor
# ---------------------------------------------------------
from pipelines.pano.modules.condyle_seg import JointPredictor as CondyleSegPredictor
from pipelines.pano.modules.condyle_detection import JointPredictor as CondyleDetPredictor
from pipelines.pano.modules.mandible_seg import MandiblePredictor
from pipelines.pano.modules.implant_detect import ImplantDetectionModule
from pipelines.pano.modules.teeth_seg import TeethSegmentationModule, process_teeth_results
from pipelines.pano.modules.rootTipDensity_detect import RootTipDensityPredictor
from pipelines.pano.modules.sinus_seg.sinus_seg_predictor import SinusSegPredictor
from pipelines.pano.modules.sinus_class.sinus_class_predictor import SinusClassPredictor

# ▼▼▼ 神经管模块 (确保您的文件名是 neural_seg_predictor.py) ▼▼▼
try:
    from pipelines.pano.modules.neural_seg.neural_seg_predictor import NeuralPredictor
except ImportError:
    logging.warning("Could not import NeuralPredictor. Neural segmentation will be skipped.")
    NeuralPredictor = None

# 导入牙齿属性 & 牙周
from pipelines.pano.modules.teeth_attribute0.teeth_attribute0_predictor import \
    TeethAttributeModule as TeethAttribute0Module
from pipelines.pano.modules.teeth_attribute1.teeth_attribute1_predictor import TeethAttributeModule
from pipelines.pano.modules.teeth_attribute2.teeth_attribute2_predictor import TeethAttribute2Module
from pipelines.pano.modules.curved_short_root.curved_short_root_predictor import CurvedShortRootModule
from pipelines.pano.modules.erupted_wisdomteeth.erupted_wisdomteeth_predictor import EruptedModule
from pipelines.pano.modules.periodontal_detect.periodontal_predictor import PeriodontalPredictor
# 导入牙槽骨分割模块
from pipelines.pano.modules.alveolarcrest import AlveolarCrestSegmentationModule

logger = logging.getLogger(__name__)

# --- 常量定义 ---
WISDOM_TEETH_FDI = [18, 28, 38, 48]
ALL_PERMANENT_TEETH_FDI = [
    11, 12, 13, 14, 15, 16, 17, 18,
    21, 22, 23, 24, 25, 26, 27, 28,
    31, 32, 33, 34, 35, 36, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48,
]
ATTRIBUTE_DESCRIPTION_MAP = {
    "area": "病灶区域", "carious_lesion": "龋坏", "curved_short_root": "牙根形态弯曲短小",
    "embedded_tooth": "埋伏牙", "erupted": "已萌出", "impacted": "阻生",
    "implant": "种植体病灶", "not_visible": "不可见", "periodontal": "牙周病灶",
    "rct_treated": "根管治疗", "residual_crown": "残冠", "residual_root": "残根",
    "restored_tooth": "修复牙", "retained_primary_tooth": "滞留乳牙",
    "root_absorption": "牙根吸收", "to_be_erupted": "待萌出",
    "tooth_germ": "牙胚", "wisdom_impaction": "智齿阻生",
}


class PanoPipeline(BasePipeline):
    def __init__(self, *, modules: dict = None):
        super().__init__()
        self.pipeline_type = "panoramic"
        self.modules = {}
        self._modules_config = modules or {}
        self.is_mock_mode = False

        logger.info("Initializing Pano Pipeline modules...")
        self._initialize_modules()

    def _get_module_config(self, module_name: str) -> dict:
        config = self._modules_config.get(module_name, {})
        return {k: v for k, v in config.items() if k != 'description'}

    def _initialize_modules(self):
        try:
            # 1. 基础骨骼与结构
            self.modules['condyle_seg'] = CondyleSegPredictor(**self._get_module_config('condyle_seg'))
            self.modules['condyle_det'] = CondyleDetPredictor(**self._get_module_config('condyle_det'))
            self.modules['mandible'] = MandiblePredictor(**self._get_module_config('mandible_seg'))
            self.modules['sinus_seg'] = SinusSegPredictor(**self._get_module_config('sinus_seg'))
            self.modules['sinus_class'] = SinusClassPredictor(**self._get_module_config('sinus_class'))

            # 2. 神经管 (容错加载)
            if NeuralPredictor:
                # 注意：这里读取的是配置里的 'neural_seg' 键，请确保 config.yaml 里改名为 neural_seg
                self.modules['neural_seg'] = NeuralPredictor(**self._get_module_config('neural_seg'))

            # 3. 牙齿与种植体
            self.modules['teeth_seg'] = TeethSegmentationModule(**self._get_module_config('teeth_seg'))
            self.modules['implant_detect'] = ImplantDetectionModule(**self._get_module_config('implant_detect'))

            # 4. 属性与病灶
            self.modules['teeth_attribute0'] = TeethAttribute0Module(**self._get_module_config('teeth_attribute0'))
            self.modules['teeth_attribute1'] = TeethAttributeModule(**self._get_module_config('teeth_attribute1'))
            self.modules['teeth_attribute2'] = TeethAttribute2Module(**self._get_module_config('teeth_attribute2'))
            self.modules['curved_short_root'] = CurvedShortRootModule(**self._get_module_config('curved_short_root'))
            self.modules['erupted_wisdomteeth'] = EruptedModule(**self._get_module_config('erupted_wisdomteeth'))
            self.modules['rootTipDensity_detect'] = RootTipDensityPredictor(
                **self._get_module_config('rootTipDensity_detect'))
            self.modules['periodontal_detect'] = PeriodontalPredictor(**self._get_module_config('periodontal_detect'))

            # 14. 牙周吸收检测模块 (periodontal_detect)
            periodontal_cfg = self._get_module_config('periodontal_detect')
            self.modules['periodontal_detect'] = PeriodontalPredictor(**periodontal_cfg)
            logger.info("  ✓ Periodontal Detection module loaded")

            # 15. 牙槽骨分割模块 (alveolarcrest_seg)
            alveolarcrest_cfg = self._get_module_config('alveolarcrest_seg')
            self.modules['alveolarcrest_seg'] = AlveolarCrestSegmentationModule(**alveolarcrest_cfg)
            logger.info("  ✓ AlveolarCrest Segmentation module loaded")

            # 显示权重信息
            self._log_weights_info()


        except (WeightFetchError, FileNotFoundError) as e:
            # 权重加载失败：本地缓存没有且S3连接失败
            logger.error(f"Failed to load model weights: {e}")
            logger.warning("Entering MOCK MODE: Will return example JSON data for all inference requests")
            self.is_mock_mode = True

            # 在mock模式下也要显示权重信息
            self._log_weights_info()
        except Exception as e:
            logger.error(f"Failed to initialize modules: {e}")
            self.is_mock_mode = True

    def run(self, image_path: str, pixel_spacing: dict = None, **kwargs) -> dict:
        if self.is_mock_mode:
            # 如果是 Mock 模式，返回空字典防止前端崩溃，或者返回测试数据
            logger.warning("Running in MOCK MODE")
            return {}

        pixel_spacing = pixel_spacing or kwargs.get("pixel_spacing")
        timer.reset()
        self._log_step("开始全景片推理", f"path={image_path}")

        self._load_image(image_path)

        try:
            # ================= 核心推理流程 =================

            # 1. 骨骼结构 (新版逻辑)
            condyle_seg_res = self._run_condyle_seg_v2(image_path)  # 髁突左右分离
            sinus_res = self._run_sinus_workflow_v2(image_path, pixel_spacing)  # 上颌窦修复版
            neural_res = self._run_neural_seg(image_path)  # ▼▼▼ 神经管 ▼▼▼

            mandible_res = self._safe_run_module_cv2(self.modules.get('mandible'), 'predict', image_path)
            condyle_det_res = self._safe_run_module(self.modules.get('condyle_det'), 'predict', image_path)

            # 2. 牙齿与种植体
            implant_res = self._safe_run_module_pil(self.modules.get('implant_detect'), 'predict', image_path)

            teeth_res = {}
            try:
                from PIL import Image
                img_pil = Image.open(image_path).convert('RGB')
                if 'teeth_seg' in self.modules:
                    raw_teeth = self.modules['teeth_seg'].predict(img_pil)
                    teeth_res = process_teeth_results(raw_teeth)
            except Exception as e:
                logger.error(f"Teeth seg error: {e}")

            # 3. 牙齿属性
            t_attr0 = self._safe_run_module_pil(self.modules.get('teeth_attribute0'), 'predict', image_path)
            t_attr1 = self._safe_run_module_pil(self.modules.get('teeth_attribute1'), 'predict', image_path)
            t_attr2 = self._safe_run_module_pil(self.modules.get('teeth_attribute2'), 'predict', image_path)
            t_curve = self._safe_run_module_pil(self.modules.get('curved_short_root'), 'predict', image_path)
            t_wisdom = self._safe_run_module_pil(self.modules.get('erupted_wisdomteeth'), 'predict', image_path)

            # 4. 其他病灶
            root_tip_res = self._safe_run_module_pil(self.modules.get('rootTipDensity_detect'), 'predict', image_path)

            # 5. 牙周 (依赖牙齿分割)
            perio_res = {}
            try:
                raw_masks = teeth_res.get("raw_masks", None)
                if raw_masks is not None and 'periodontal_detect' in self.modules:
                    class_names = [t.get("class_name", "") for t in teeth_res.get("detected_teeth", [])]
                    orig_shape = teeth_res.get("original_shape", None)
                    inp = {"masks": raw_masks, "class_names": class_names, "original_shape": orig_shape}
                    perio_res = self.modules['periodontal_detect'].predict(image_path=image_path, teeth_seg_results=inp)
            except Exception as e:
                logger.error(f"Periodontal error: {e}")

            # 2.13 牙槽骨分割
            alveolarcrest_results = self._run_alveolarcrest_seg(image_path)

        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise

        # 3. 牙位属性整合
        logger.info("Analyzing teeth attributes...")
        try:
            teeth_analysis = self._analyze_teeth_and_attributes(
                teeth_res or {}, t_attr0, t_attr1, t_attr2, t_curve, t_wisdom
            )
            if teeth_res is None: teeth_res = {}
            teeth_res.update(teeth_analysis)
        except Exception as e:
            logger.error(f"Teeth analysis error: {e}")

        # 4. 收集结果
        inference_results = {
            "condyle_seg": condyle_seg_res,
            "condyle_det": condyle_det_res,
            "neural_seg": neural_res,  # 加入神经管
            "mandible": mandible_res,
            "implant": implant_res,
            "teeth": teeth_res,
            "sinus": sinus_res,
            "teeth_attribute0": t_attr0, "teeth_attribute1": t_attr1, "teeth_attribute2": t_attr2,
            "curved_short_root": t_curve, "erupted_wisdomteeth": t_wisdom,
            "rootTipDensity": root_tip_res, "periodontal": perio_res
        }

        # 5. 生成报告
        image_name = image_path.split("/")[-1] if "/" in image_path else image_path.split("\\")[-1]
        metadata = {
            "ImageName": image_name,
            "DiagnosisID": f"AI-DX-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "AnalysisTime": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        with timer.record("report.generation"):
            data_dict = pano_report_utils.generate_standard_output(
                metadata, inference_results, pixel_spacing=pixel_spacing
            )

        timer.print_report()
        return data_dict

    # -------------------------------------------------------------------------
    # 神经管分割 (新)
    # -------------------------------------------------------------------------
    def _run_neural_seg(self, image_path: str) -> dict:
        self._log_step("神经管分割", "ONNX + 左右分离")
        try:
            if 'neural_seg' not in self.modules:
                return {}

            image = cv2.imread(image_path)
            if image is None: return {}

            predictor = self.modules['neural_seg']
            result = predictor.predict(image)

            # 【重要安全措施】
            # 清理掉 Numpy Mask 数组，防止 JSON 序列化崩溃
            if result and 'raw_features' in result:
                for side in ['left', 'right']:
                    if side in result['raw_features']:
                        # pop 既删除又不会报错（如果key不存在）
                        result['raw_features'][side].pop('mask', None)

            return result

        except Exception as e:
            logger.error(f"Neural seg failed: {e}")
            return {}

    # -------------------------------------------------------------------------
    # 髁突分割 (V2)
    # -------------------------------------------------------------------------
    def _run_condyle_seg_v2(self, image_path: str) -> dict:
        self._log_step("髁突分割", "v2: 左右分离")
        try:
            if 'condyle_seg' not in self.modules: return {}

            # 动态导入防止循环引用
            from pipelines.pano.modules.condyle_seg.pre_post import JointPrePostProcessor

            image = cv2.imread(image_path)
            if image is None: return {}

            predictor = self.modules['condyle_seg']
            if hasattr(predictor, 'pre_post'):
                pre_post = predictor.pre_post
            else:
                pre_post = JointPrePostProcessor(input_size=(224, 224))

            input_tensor = pre_post.preprocess(image)
            if not predictor.session: return {}

            input_name = predictor.session.get_inputs()[0].name
            raw_out = predictor.session.run(None, {input_name: input_tensor.numpy()})

            final_result = pre_post.postprocess(raw_out[0])

            # 清洗 Mask
            if 'raw_features' in final_result:
                for side in ['left', 'right']:
                    if side in final_result['raw_features']:
                        final_result['raw_features'][side].pop('mask', None)

            return final_result

        except Exception as e:
            logger.error(f"Condyle seg v2 failed: {e}")
            return {}

    # -------------------------------------------------------------------------
    # 上颌窦工作流 (V2 修复版)
    # -------------------------------------------------------------------------
    def _run_sinus_workflow_v2(self, image_path, pixel_spacing):
        self._log_step("上颌窦分析", "v2: 轮廓修复版")
        try:
            if 'sinus_seg' not in self.modules or 'sinus_class' not in self.modules: return {}

            image = cv2.imread(image_path)
            if image is None: return {}

            seg_predictor = self.modules['sinus_seg']
            cls_predictor = self.modules['sinus_class']

            if hasattr(seg_predictor, 'pre_post'):
                pre_post = seg_predictor.pre_post
            else:
                from pipelines.pano.modules.sinus_seg.pre_post import SinusPrePostProcessor
                pre_post = SinusPrePostProcessor(seg_size=(512, 512))

            seg_res = seg_predictor.predict(image)
            raw_output = seg_res.get('debug_raw')
            if raw_output is None: raw_output = seg_res.get('mask')
            if raw_output is None: return {}

            crops_info = pre_post.process_segmentation_result(raw_output, image)

            results_list = []
            masks_info = []

            for item in crops_info:
                loc = item['location']
                crop = item['crop']
                bbox = item['bbox']
                contour = item.get('contour', [])

                is_inflam = False
                conf = 0.0
                if crop.size > 0:
                    cls_res = cls_predictor.predict(crop)
                    is_inflam = cls_res.get('is_inflam', False)
                    conf = cls_res.get('confidence', 0.0)

                cn_side = "左" if loc == "Left" else "右"
                detail = f"{cn_side}上颌窦" + ("可见炎症影像。" if is_inflam else "气化良好。")

                results_list.append({
                    "Side": loc.lower(),
                    "Pneumatization": 0,
                    "Inflammation": is_inflam,
                    "Detail": detail,
                    "Confidence": conf
                })

                # 强制类型转换，防止 JSON 崩溃
                safe_contour = []
                for pt in contour:
                    safe_contour.append([int(pt[0]), int(pt[1])])

                masks_info.append({
                    "label": f"sinus_{loc.lower()}",
                    "bbox": [int(b) for b in bbox],
                    "contour": safe_contour
                })

            return {"MaxillarySinus": results_list, "masks_info": masks_info}

        except Exception as e:
            logger.error(f"Sinus workflow v2 error: {e}")
            import traceback
            traceback.print_exc()
            return {}

    # -------------------------------------------------------------------------
    # 辅助函数
    # -------------------------------------------------------------------------
    def _safe_run_module(self, module, func, arg):
        try:
            if module: return getattr(module, func)(arg)
        except:
            return {}
        return {}

    def _safe_run_module_cv2(self, module, func, path):
        try:
            if module: return getattr(module, func)(cv2.imread(path))
        except:
            return {}
        return {}

    def _safe_run_module_pil(self, module, func, path):
        try:
            if module:
                from PIL import Image
                return getattr(module, func)(Image.open(path).convert('RGB'))
        except:
            return {}
        return {}

    # -------------------------------------------------------------------------
    # 牙位分析逻辑 (完整保留)
    # -------------------------------------------------------------------------
    def _analyze_teeth_and_attributes(
            self,
            teeth_results: dict,
            teeth_attr0: dict,
            teeth_attr1: dict,
            teeth_attr2: dict,
            curved_short_root: dict,
            erupted_wisdomteeth: dict,
            iou_threshold: float = 0.2,
    ) -> dict:
        from collections import defaultdict

        detected_teeth = teeth_results.get("detected_teeth", [])
        raw_masks = teeth_results.get("raw_masks", None)
        original_image_shape = teeth_results.get("image_shape", None)

        if original_image_shape is None:
            for res in [teeth_attr1, teeth_attr2, curved_short_root]:
                if res and "image_shape" in res:
                    original_image_shape = res["image_shape"]
                    break
        if original_image_shape is None:
            original_image_shape = teeth_results.get("original_shape", None)

        tooth_bboxes = {}

        if raw_masks is not None and len(detected_teeth) > 0:
            mask_h, mask_w = None, None
            if isinstance(raw_masks, np.ndarray) and raw_masks.ndim >= 2:
                mask_h = raw_masks.shape[1] if raw_masks.ndim == 3 else raw_masks.shape[0]
                mask_w = raw_masks.shape[2] if raw_masks.ndim == 3 else raw_masks.shape[1]
            elif isinstance(raw_masks, list) and len(raw_masks) > 0:
                mask_h, mask_w = raw_masks[0].shape[:2]

            scale_x, scale_y = 1.0, 1.0
            if original_image_shape and mask_h:
                orig_h, orig_w = original_image_shape[:2]
                scale_x = orig_w / mask_w
                scale_y = orig_h / mask_h

            for tooth in detected_teeth:
                fdi = tooth.get("fdi")
                mask_idx = tooth.get("mask_index", -1)
                if not fdi or mask_idx < 0: continue

                if isinstance(raw_masks, np.ndarray):
                    mask = raw_masks[mask_idx]
                else:
                    mask = raw_masks[mask_idx]

                try:
                    ys, xs = np.where(mask > 0.5)
                    if ys.size == 0: continue
                    tooth_bboxes[fdi] = [
                        int(xs.min() * scale_x), int(ys.min() * scale_y),
                        int(xs.max() * scale_x), int(ys.max() * scale_y)
                    ]
                except:
                    pass

        all_attr_boxes = []
        for mod_res in [teeth_attr0, teeth_attr1, teeth_attr2, curved_short_root, erupted_wisdomteeth]:
            if not mod_res: continue
            boxes = mod_res.get("boxes", [])
            names = mod_res.get("attribute_names", [])
            confs = mod_res.get("confidences", [])

            if not names and "attributes_detected" in mod_res:
                names = [x.get("attribute") for x in mod_res["attributes_detected"]]

            min_len = min(len(boxes), len(names), len(confs))
            for i in range(min_len):
                all_attr_boxes.append((boxes[i], names[i], float(confs[i])))

        tooth_attributes = defaultdict(list)

        def bbox_iou(box1, box2):
            x1, y1, x2, y2 = box1
            x1g, y1g, x2g, y2g = box2
            inter_x1 = max(x1, x1g)
            inter_y1 = max(y1, y1g)
            inter_x2 = min(x2, x2g)
            inter_y2 = min(y2, y2g)
            if inter_x2 <= inter_x1 or inter_y2 <= inter_y1: return 0.0
            inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
            union = ((x2 - x1) * (y2 - y1)) + ((x2g - x1g) * (y2g - y1g)) - inter
            return inter / union if union > 0 else 0.0

        for attr_box, attr_name, conf in all_attr_boxes:
            best_fdi, best_iou = None, 0.0
            for fdi, tooth_box in tooth_bboxes.items():
                iou = bbox_iou(attr_box, tooth_box)
                if iou > best_iou:
                    best_iou = iou
                    best_fdi = fdi
            if best_fdi and best_iou >= iou_threshold:
                tooth_attributes[best_fdi].append((attr_name, conf))

        detected_set = set(tooth_bboxes.keys())
        missing_teeth = []
        for fdi in ALL_PERMANENT_TEETH_FDI:
            if fdi not in detected_set:
                missing_teeth.append({"FDI": fdi, "Reason": "missing", "Detail": f"牙位 {fdi} 未检测到"})

        third_molar_summary = {}
        for fdi in WISDOM_TEETH_FDI:
            if fdi in detected_set:
                attrs = [x[0] for x in tooth_attributes.get(fdi, [])]
                if "erupted" in attrs:
                    summary = {"Level": 0, "Detail": "已萌出", "Confidence": 0.85}
                elif "wisdom_impaction" in attrs or "impacted" in attrs:
                    summary = {"Level": 1, "Detail": "阻生", "Confidence": 0.85}
                else:
                    summary = {"Level": 2, "Detail": "已检测到", "Confidence": 0.70}
            else:
                summary = {"Level": 4, "Detail": "未见智齿", "Confidence": 0.0}
            third_molar_summary[fdi] = summary

        tooth_attributes_formatted = {}
        for fdi, attr_list in tooth_attributes.items():
            formatted = []
            for name, conf in attr_list:
                formatted.append({
                    "Value": name,
                    "Description": ATTRIBUTE_DESCRIPTION_MAP.get(name, name),
                    "Confidence": round(conf, 2)
                })
            tooth_attributes_formatted[fdi] = formatted

        return {
            "MissingTeeth": missing_teeth,
            "ThirdMolarSummary": third_molar_summary,
            "ToothAttributes": tooth_attributes_formatted
        }

    def _collect_results(self, **kwargs):
        return kwargs