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

    # 图像几何/像素信息，依次是高度，宽度，像素间距，图像方向，图像位置
    meta["Rows"] = getattr(ds, "Rows", None)
    meta["Columns"] = getattr(ds, "Columns", None)
    meta["PixelSpacing"] = _get(ds, "PixelSpacing", None)
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
    dicom_path = r"D:\git-615\Teeth\Xray-inference\tools\CTX.dcm"
    out_dir = r"D:\git-615\Teeth\Xray-inference\tools\converted"
    quality = 95
    meta, jpg_path = convert_dicom(dicom_path, out_dir,quality)
    print(meta)
    print(jpg_path)
