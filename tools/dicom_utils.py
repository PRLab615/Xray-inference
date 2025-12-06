# -*- coding: utf-8 -*-
"""
DICOM 工具脚本

功能：
1) 识别并读取 DICOM 文件
2) 提取关键元数据，返回为 Python 字典
3) 将 DICOM 图像转换为 JPG 并保存到磁盘
用法：meta, jpg_path = convert_dicom(dicom_path, out_dir, quality)
"""
from __future__ import annotations

from typing import Any, Dict, Tuple, Optional
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import pydicom
    from pydicom.pixel_data_handlers.util import apply_voi_lut  # type: ignore
except Exception as e:  # pragma: no cover
    raise ImportError(
        "pydicom 未安装或版本不兼容，请在 requirements.txt 中添加 pydicom 并安装依赖。"
    )


# ------------------------- 基础能力 -------------------------

def is_dicom(path: str | Path) -> bool:
    """粗略判断文件是否为 DICOM。

    规则：
    - 先检查扩展名（.dcm 或无扩展名时也可能是 DICOM）
    - 尝试用 pydicom.dcmread 读取前 1KB 头信息
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False

    try:
        # force=True 避免因为某些不规范文件头而失败
        _ = pydicom.dcmread(str(p), stop_before_pixels=True, force=True)
        return True
    except Exception:
        return False


def load_dicom(path: str | Path) -> "pydicom.FileDataset":
    """读取 DICOM，返回 FileDataset。"""
    return pydicom.dcmread(str(path), force=True)


# ------------------------- 元数据提取 -------------------------

def _get(ds: "pydicom.FileDataset", key: str, default: Any = None) -> Any:
    """安全读取 DICOM 字段，自动转为 Python 基本类型。

    规则：
    - 若值为 list/tuple（如 MultiValue），逐项转为字符串
    - 其他复杂类型统一转为字符串（避免将字符串当作可迭代拆成字符）
    - 基本数字类型保持原样
    """
    if not hasattr(ds, key):
        return default
    val = getattr(ds, key)
    try:
        if isinstance(val, (list, tuple)):
            return [str(x) for x in val]
        if isinstance(val, (int, float)):
            return val
        # 其余（包括 PersonName、DS/IS、UID 等）统一 str()
        return str(val)
    except Exception:
        return default


def extract_metadata(ds: "pydicom.FileDataset") -> Dict[str, Any]:
    """提取常见 DICOM 元数据，返回字典。"""
    meta: Dict[str, Any] = {}

    # 患者相关，依次是姓名，ID，性别，出生日期
    meta["PatientName"] = _get(ds, "PatientName", "")
    meta["PatientID"] = _get(ds, "PatientID", "")
    meta["PatientSex"] = _get(ds, "PatientSex", "")
    meta["PatientBirthDate"] = _get(ds, "PatientBirthDate", "")

    # 检查/序列相关，依次是日期，时间，序列描述，模态，检查部位
    meta["StudyDate"] = _get(ds, "StudyDate", "")
    meta["StudyTime"] = _get(ds, "StudyTime", "")
    meta["SeriesDescription"] = _get(ds, "SeriesDescription", "")
    meta["Modality"] = _get(ds, "Modality", "")
    meta["BodyPartExamined"] = _get(ds, "BodyPartExamined", "")

    # 医院名称
    meta["InstitutionName"] = _get(ds, "InstitutionName", "")

    # UID 相关，依次是检查的唯一ID、图像的唯一ID
    meta["StudyInstanceUID"] = _get(ds, "StudyInstanceUID", "")
    meta["SOPInstanceUID"] = _get(ds, "SOPInstanceUID", "")

    # 图像几何/像素信息，依次是高度，宽度
    meta["Rows"] = getattr(ds, "Rows", None)
    meta["Columns"] = getattr(ds, "Columns", None)

    # --- 【关键】比例尺提取逻辑 ---
    # PixelSpacing (0028,0030): 经过校准后的像素间距 [行间距, 列间距] (mm)
    # ImagerPixelSpacing (0018,1164): 探测器面板上的物理像素间距（备选）
    # EstimatedRadiographicMagnificationFactor (0018,1114): 放大率因子
    pixel_spacing = getattr(ds, "PixelSpacing", None)
    imager_pixel_spacing = getattr(ds, "ImagerPixelSpacing", None)
    magnification_factor = getattr(ds, "EstimatedRadiographicMagnificationFactor", None)

    # 优先使用 PixelSpacing，其次使用 ImagerPixelSpacing
    effective_spacing = pixel_spacing if pixel_spacing else imager_pixel_spacing
    spacing_source = "PixelSpacing" if pixel_spacing else ("ImagerPixelSpacing" if imager_pixel_spacing else None)

    if effective_spacing and len(effective_spacing) >= 2:
        try:
            # 将 Decimal 或字符串转为 float
            spacing_y = float(effective_spacing[0])  # 垂直方向 1 pixel 代表多少 mm
            spacing_x = float(effective_spacing[1])  # 水平方向 1 pixel 代表多少 mm

            meta["PixelSpacing"] = [spacing_y, spacing_x]
            meta["PixelSpacingSource"] = spacing_source

            # 处理放大率校正（如果存在）
            # 真实大小 = 测量像素数 × PixelSpacing / 放大率
            if magnification_factor:
                try:
                    mag = float(magnification_factor)
                    if mag > 0:
                        meta["MagnificationFactor"] = mag
                        # 校正后的比例尺
                        meta["Pixel2MM_Scale"] = spacing_x / mag
                        meta["Pixel2MM_Scale_Y"] = spacing_y / mag
                        meta["Pixel2MM_Corrected"] = True
                    else:
                        meta["MagnificationFactor"] = None
                        meta["Pixel2MM_Scale"] = spacing_x
                        meta["Pixel2MM_Scale_Y"] = spacing_y
                        meta["Pixel2MM_Corrected"] = False
                except (ValueError, TypeError):
                    meta["MagnificationFactor"] = None
                    meta["Pixel2MM_Scale"] = spacing_x
                    meta["Pixel2MM_Scale_Y"] = spacing_y
                    meta["Pixel2MM_Corrected"] = False
            else:
                meta["MagnificationFactor"] = None
                meta["Pixel2MM_Scale"] = spacing_x  # 水平方向：1像素 = 多少mm
                meta["Pixel2MM_Scale_Y"] = spacing_y  # 垂直方向：1像素 = 多少mm
                meta["Pixel2MM_Corrected"] = False
        except (ValueError, TypeError, IndexError):
            meta["PixelSpacing"] = None
            meta["PixelSpacingSource"] = None
            meta["MagnificationFactor"] = None
            meta["Pixel2MM_Scale"] = None
            meta["Pixel2MM_Scale_Y"] = None
            meta["Pixel2MM_Corrected"] = False
    else:
        meta["PixelSpacing"] = None
        meta["PixelSpacingSource"] = None
        meta["MagnificationFactor"] = None
        meta["Pixel2MM_Scale"] = None  # 无法获取比例尺
        meta["Pixel2MM_Scale_Y"] = None
        meta["Pixel2MM_Corrected"] = False

    # 图像方向和位置
    meta["ImageOrientationPatient"] = _get(ds, "ImageOrientationPatient", None)
    meta["ImagePositionPatient"] = _get(ds, "ImagePositionPatient", None)

    # 像素属性，依次是通道数，颜色模式
    meta["SamplesPerPixel"] = getattr(ds, "SamplesPerPixel", None)
    meta["PhotometricInterpretation"] = _get(ds, "PhotometricInterpretation", "")

    # 图像显示参数，依次是图像对比度中心，图像对比度宽度，重标定斜率，重标定截距
    meta["WindowCenter"] = _get(ds, "WindowCenter", None)
    meta["WindowWidth"] = _get(ds, "WindowWidth", None)
    meta["RescaleSlope"] = getattr(ds, "RescaleSlope", None)
    meta["RescaleIntercept"] = getattr(ds, "RescaleIntercept", None)

    return meta


# ------------------------- DICOM 到 PatientInfo 转换 -------------------------

def extract_patient_info_for_ceph(ds: "pydicom.FileDataset") -> Dict[str, Any]:
    """
    从 DICOM 数据集中提取患者信息，转换为侧位片推理所需的格式
    
    提取规则：
    - gender: 从 PatientSex (0010,0040) 提取，M -> Male, F -> Female
    - DentalAgeStage: 默认为 Permanent（DICOM 中通常没有牙期字段）
    
    返回格式与 server/schemas.py 中的 PatientInfo 兼容：
    {
        "gender": "Male" | "Female",
        "DentalAgeStage": "Permanent" | "Mixed"
    }
    
    Args:
        ds: pydicom.FileDataset 对象
        
    Returns:
        dict: 患者信息字典，可直接用于侧位片推理
        
    注意：
        - 如果 DICOM 中没有 PatientSex 或值无法识别，返回 None
        - DentalAgeStage 默认为 Permanent，因为 DICOM 标准中没有对应字段
    """
    result: Dict[str, Any] = {}
    
    # 提取性别
    patient_sex = getattr(ds, "PatientSex", None)
    if patient_sex:
        sex_str = str(patient_sex).upper().strip()
        if sex_str == "M":
            result["gender"] = "Male"
        elif sex_str == "F":
            result["gender"] = "Female"
        else:
            # 未知性别，尝试其他常见格式
            if sex_str in ["MALE", "男"]:
                result["gender"] = "Male"
            elif sex_str in ["FEMALE", "女"]:
                result["gender"] = "Female"
            else:
                result["gender"] = None  # 无法识别
    else:
        result["gender"] = None
    
    # DentalAgeStage：DICOM 标准中没有对应字段，默认为 Permanent
    # 如果需要 Mixed（混合牙列期），需要客户端手动指定
    result["DentalAgeStage"] = "Permanent"
    
    return result


def extract_dicom_info_for_inference(
    dicom_path: str | Path,
    out_dir: Optional[str | Path] = None,
    quality: int = 95,
) -> Dict[str, Any]:
    """
    从 DICOM 文件中提取推理所需的所有信息
    
    一站式函数，返回：
    1. 转换后的 JPG 图像路径
    2. 患者信息（用于侧位片）
    3. 比例尺信息（像素到毫米的转换）
    4. 完整的 DICOM 元数据
    
    Args:
        dicom_path: DICOM 文件路径
        out_dir: 输出目录（可选），不传则与 DICOM 同目录
        quality: JPG 质量（默认 95）
        
    Returns:
        dict: 包含以下字段的字典
            - image_path: 转换后的 JPG 图像路径
            - patient_info: 患者信息（gender, DentalAgeStage）
            - pixel_spacing: 比例尺信息（scale_x, scale_y, available, corrected）
            - dicom_metadata: 完整的 DICOM 元数据
            
    示例：
        info = extract_dicom_info_for_inference("scan.dcm")
        if info["patient_info"]["gender"]:
            # 使用提取的患者信息
            patient_info = info["patient_info"]
        if info["pixel_spacing"]["available"]:
            # 使用提取的比例尺
            scale = info["pixel_spacing"]["scale_x"]
    """
    # 1. 转换 DICOM 到 JPG，同时获取元数据
    meta, jpg_path = dicom_to_jpeg(dicom_path, out_dir=out_dir, quality=quality)
    
    # 2. 重新加载 DICOM 提取患者信息（使用原始 ds 对象）
    ds = load_dicom(dicom_path)
    patient_info = extract_patient_info_for_ceph(ds)
    
    # 3. 提取比例尺信息
    scale_info = get_scale_info(meta)
    
    return {
        "image_path": jpg_path,
        "patient_info": patient_info,
        "pixel_spacing": {
            "available": scale_info["available"],
            "scale_x": scale_info["scale_x"],
            "scale_y": scale_info["scale_y"],
            "corrected": scale_info["corrected"],
            "magnification": scale_info["magnification"],
            "source": scale_info["source"],
        },
        "dicom_metadata": meta,
    }


# ------------------------- 比例尺计算辅助函数 -------------------------

def pixels_to_mm(
    pixel_distance: float,
    pixel_spacing: float,
    magnification_factor: Optional[float] = None,
) -> float:
    """
    将像素距离转换为实际物理距离（毫米）。

    参数：
    - pixel_distance: 像素距离（像素数）
    - pixel_spacing: 像素间距（mm/pixel），来自 DICOM PixelSpacing
    - magnification_factor: 放大率因子（可选），若有则自动校正

    返回：
    - 实际物理距离（毫米）

    示例：
        # 假设 PixelSpacing = 0.148 mm/pixel
        real_length = pixels_to_mm(100, 0.148)  # 返回 14.8 mm
    """
    if magnification_factor and magnification_factor > 0:
        return pixel_distance * pixel_spacing / magnification_factor
    return pixel_distance * pixel_spacing


def mm_to_pixels(
    mm_distance: float,
    pixel_spacing: float,
    magnification_factor: Optional[float] = None,
) -> float:
    """
    将实际物理距离（毫米）转换为像素距离。

    参数：
    - mm_distance: 实际物理距离（毫米）
    - pixel_spacing: 像素间距（mm/pixel），来自 DICOM PixelSpacing
    - magnification_factor: 放大率因子（可选），若有则自动校正

    返回：
    - 像素距离

    示例：
        # 假设 PixelSpacing = 0.148 mm/pixel
        pixel_length = mm_to_pixels(14.8, 0.148)  # 返回 100 像素
    """
    if pixel_spacing <= 0:
        raise ValueError("pixel_spacing 必须大于 0")
    if magnification_factor and magnification_factor > 0:
        return mm_distance * magnification_factor / pixel_spacing
    return mm_distance / pixel_spacing


def get_scale_info(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    从元数据字典中提取比例尺相关信息的便捷函数。

    参数：
    - meta: extract_metadata 返回的元数据字典

    返回：
    - 包含比例尺信息的字典：
        - available: 比例尺是否可用
        - scale_x: 水平方向 1像素 = 多少mm
        - scale_y: 垂直方向 1像素 = 多少mm
        - corrected: 是否经过放大率校正
        - magnification: 放大率（如果有）
        - source: 数据来源（PixelSpacing 或 ImagerPixelSpacing）
    """
    scale_x = meta.get("Pixel2MM_Scale")
    scale_y = meta.get("Pixel2MM_Scale_Y")

    return {
        "available": scale_x is not None,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "corrected": meta.get("Pixel2MM_Corrected", False),
        "magnification": meta.get("MagnificationFactor"),
        "source": meta.get("PixelSpacingSource"),
    }


# ------------------------- 图像转换 -------------------------

def _to_uint8(img: np.ndarray) -> np.ndarray:
    """将任意 dtype/范围的图像归一化为 0-255 的 uint8。"""
    img = img.astype(np.float32)
    min_v = np.min(img)
    img = img - min_v
    max_v = np.max(img)
    if max_v > 0:
        img = img / max_v
    img = (img * 255.0).clip(0, 255).astype(np.uint8)
    return img


def _dicom_to_ndarray(ds: "pydicom.FileDataset") -> np.ndarray:
    """将 DICOM 数据集映射为 numpy 图像阵列（已应用 LUT/窗宽窗位/重标定）。"""
    arr = ds.pixel_array  # 可能需要 pylibjpeg/gdcm 以解压压缩像素

    # 应用重标定
    slope = getattr(ds, "RescaleSlope", 1) or 1
    intercept = getattr(ds, "RescaleIntercept", 0) or 0
    try:
        arr = arr.astype(np.float32) * float(slope) + float(intercept)
    except Exception:
        arr = arr.astype(np.float32)

    # 应用 VOI LUT（窗宽窗位）
    try:
        arr = apply_voi_lut(arr, ds)
    except Exception:
        # 无可用 LUT/窗宽窗位
        pass

    # 单通道图像时的反转（MONOCHROME1 需要反色）
    photometric = getattr(ds, "PhotometricInterpretation", "").upper()
    if photometric == "MONOCHROME1":
        arr = np.max(arr) - arr

    return arr


def dicom_to_jpeg(
    dicom_path: str | Path,
    out_dir: Optional[str | Path] = None,
    out_path: Optional[str | Path] = None,
    quality: int = 95,
) -> Tuple[Dict[str, Any], str]:
    """
    将 DICOM 转换为 JPG，并返回 (元数据字典, 输出 JPG 路径)。

    参数：
    - dicom_path: 输入 DICOM 文件路径
    - out_dir: 可选，输出目录；若提供 out_path，则忽略该参数
    - out_path: 可选，精确指定输出 JPG 文件路径
    - quality: JPG 质量（1-100）
    """
    dicom_path = Path(dicom_path)
    if not dicom_path.exists():
        raise FileNotFoundError(f"DICOM 文件不存在: {dicom_path}")

    ds = load_dicom(dicom_path)
    meta = extract_metadata(ds)

    # 转到 numpy 数组
    np_img = _dicom_to_ndarray(ds)

    # 处理通道
    pil_mode = "L"
    if np_img.ndim == 2:
        img_u8 = _to_uint8(np_img)
        pil_img = Image.fromarray(img_u8, mode="L")
    elif np_img.ndim == 3 and np_img.shape[-1] in (3, 4):
        # 假设末轴为通道
        if np_img.shape[-1] == 4:
            np_img = np_img[..., :3]
        img_u8 = _to_uint8(np_img)
        pil_img = Image.fromarray(img_u8, mode="RGB")
        pil_mode = "RGB"
    else:
        # 其他非常规形状，尝试压缩为灰度
        img_u8 = _to_uint8(np.squeeze(np_img))
        pil_img = Image.fromarray(img_u8, mode="L")

    # 计算输出路径
    if out_path is not None:
        out_jpg = Path(out_path)
    else:
        base = dicom_path.stem or dicom_path.name
        target_dir = Path(out_dir) if out_dir is not None else dicom_path.parent
        out_jpg = target_dir / f"{base}.jpg"

    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    pil_img.save(str(out_jpg), format="JPEG", quality=quality, optimize=True)

    # 追加部分导出信息
    meta_export = {
        **meta,
        "Export": {
            "OutputJPEG": str(out_jpg),
            "Width": pil_img.width,
            "Height": pil_img.height,
            "Mode": pil_mode,
            "Quality": quality,
        },
    }

    return meta_export, str(out_jpg)


def convert_dicom(
    dicom_path: str | Path,
    out_dir: Optional[str | Path] = None,
    quality: int = 95,
) -> Tuple[Dict[str, Any], str]:
    """
    一次调用完成 DICOM 读取、元数据提取、JPG 转换并返回
    用法：meta, jpg_path = convert_dicom(dicom_path, out_dir, quality)

    - dicom_path: 输入 DICOM 文件路径
    - out_dir: 可选，输出目录；不传则与 DICOM 同目录
    - quality: JPG 质量（默认 95）
    - 返回：(元数据字典, JPG 路径)
    """
    return dicom_to_jpeg(dicom_path, out_dir=out_dir, out_path=None, quality=quality)


# ------------------------- 命令行用法 -------------------------
if __name__ == "__main__":
    dicom_path = r"D:\硕士文档\项目\口腔\DICOM\I1.dcm"
    out_dir = r"D:\硕士文档\项目\口腔\DICOM\converted"
    quality = 95
    meta, jpg_path = convert_dicom(dicom_path, out_dir, quality)

    print("=" * 50)
    print("DICOM 元数据：")
    print("=" * 50)
    for key, value in meta.items():
        print(f"  {key}: {value}")

    print("\n" + "=" * 50)
    print("比例尺信息：")
    print("=" * 50)
    scale_info = get_scale_info(meta)
    if scale_info["available"]:
        print(f"  比例尺可用: 是")
        print(f"  水平方向: 1像素 = {scale_info['scale_x']:.4f} mm")
        print(f"  垂直方向: 1像素 = {scale_info['scale_y']:.4f} mm")
        print(f"  数据来源: {scale_info['source']}")
        print(f"  放大率校正: {'是' if scale_info['corrected'] else '否'}")
        if scale_info['magnification']:
            print(f"  放大率因子: {scale_info['magnification']}")

        # 示例：假设测量了一颗牙齿的像素长度为 100 像素
        example_pixels = 100
        real_mm = pixels_to_mm(example_pixels, scale_info['scale_x'])
        print(f"\n  示例计算: {example_pixels} 像素 = {real_mm:.2f} mm")
    else:
        print(f"  比例尺可用: 否（该 DICOM 文件未包含 PixelSpacing 信息）")

    print("\n" + "=" * 50)
    print(f"输出 JPG: {jpg_path}")
    print("=" * 50)
