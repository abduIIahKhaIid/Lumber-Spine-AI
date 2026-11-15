"""DICOM reading, in-memory de-identification and series classification."""

from __future__ import annotations

import re
from io import BytesIO

import numpy as np
import pydicom
from pydicom.dataset import Dataset

MR_IMAGE_UID_PREFIX = "1.2.840.10008.5.1.4.1.1.4"
NON_LUMBAR = re.compile(
    r"\b(cervical|thoracic|brain|head|neck|knee|hip|shoulder|abdomen|pelvis|chest"
    r"|c[ -]?spine|t[ -]?spine|cspine|tspine)\b",
    re.IGNORECASE,
)
LUMBAR = re.compile(r"\b(lumbar|lumbosacral|l[ -]?spine|lspine)\b", re.IGNORECASE)

# Identifying attributes removed before any processing. Group 0x0010 (patient) is removed
# entirely; these are the remaining common identifiers outside it.
IDENTIFYING_KEYWORDS = (
    "AccessionNumber",
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "PhysiciansOfRecord",
    "NameOfPhysiciansReadingStudy",
    "RequestingPhysician",
    "StationName",
    "DeviceSerialNumber",
    "StudyID",
    "OtherPatientIDs",
    "RequestAttributesSequence",
)

SUPPORTED = {
    ("Sagittal", "T2"): "SCS",
    ("Sagittal", "STIR"): "SCS",
    ("Sagittal", "T1"): "NFN",
    ("Axial", "T2"): "SS",
}
CONDITION_NAMES = {
    "SCS": "Spinal canal stenosis",
    "NFN": "Neural foraminal narrowing",
    "SS": "Subarticular stenosis",
}


class UnsupportedScan(ValueError):
    """The upload is readable but not something these models were trained on."""


def read_dataset(data: bytes | BytesIO, *, force: bool = False) -> Dataset:
    stream = data if isinstance(data, BytesIO) else BytesIO(data)
    try:
        return pydicom.dcmread(stream, force=force)
    except Exception as exc:  # pydicom raises several unrelated types
        raise UnsupportedScan("The file could not be read as DICOM.") from exc


def deidentify(dataset: Dataset) -> Dataset:
    """Strip patient and staff identifiers in memory; nothing is written to disk."""
    for element in list(dataset):
        if element.tag.group == 0x0010 or element.tag.is_private:
            del dataset[element.tag]
    for keyword in IDENTIFYING_KEYWORDS:
        if keyword in dataset:
            delattr(dataset, keyword)
    return dataset


def lumbar_status(dataset: Dataset) -> bool:
    """Reject explicit non-MR or non-lumbar studies. Returns True when lumbar is named."""
    modality = str(getattr(dataset, "Modality", "") or "").upper()
    sop = str(
        getattr(dataset, "SOPClassUID", "")
        or getattr(getattr(dataset, "file_meta", None), "MediaStorageSOPClassUID", "")
    )
    if modality and modality != "MR":
        raise UnsupportedScan("Only lumbar MR DICOM images are supported.")
    if sop and not sop.startswith(MR_IMAGE_UID_PREFIX):
        raise UnsupportedScan("Only MR image storage objects are supported.")
    anatomy = " ".join(
        str(getattr(dataset, name, "") or "")
        for name in ("BodyPartExamined", "StudyDescription", "SeriesDescription", "ProtocolName")
    )
    if NON_LUMBAR.search(anatomy):
        raise UnsupportedScan("This scan metadata identifies a non-lumbar body region.")
    return bool(LUMBAR.search(anatomy))


def detect_plane(orientation) -> str:
    if not orientation or len(orientation) != 6:
        return "Unknown"
    row = np.asarray([float(v) for v in orientation[:3]])
    col = np.asarray([float(v) for v in orientation[3:]])
    return ("Sagittal", "Coronal", "Axial")[int(np.argmax(np.abs(np.cross(row, col))))]


def detect_sequence(dataset: Dataset) -> str:
    text = " ".join(
        str(getattr(dataset, name, "") or "") for name in ("ProtocolName", "SeriesDescription")
    ).lower()
    if re.search(r"\bt2\b|\bt2w\b|t2-weighted|\bt2_", text):
        return "T2"
    if re.search(r"\bt1\b|\bt1w\b|t1-weighted|\bt1_", text):
        return "T1"
    if "stir" in text:
        return "STIR"
    return "Unknown"


def classify(dataset: Dataset) -> dict:
    plane = detect_plane(getattr(dataset, "ImageOrientationPatient", None))
    sequence = detect_sequence(dataset)
    condition = SUPPORTED.get((plane, sequence), "Unknown")
    return {"condition": condition, "plane": plane, "sequence": sequence}


def require_supported(info: dict) -> str:
    if info["condition"] == "Unknown":
        raise UnsupportedScan(
            f"Unsupported series ({info['plane']} {info['sequence']}). Use sagittal T1, "
            "sagittal T2/STIR or axial T2 lumbar MRI, with the sequence named in the "
            "series description."
        )
    return info["condition"]


def pixels(dataset: Dataset) -> np.ndarray:
    try:
        image = dataset.pixel_array
    except Exception as exc:
        raise UnsupportedScan("DICOM pixel data could not be decoded.") from exc
    if image.ndim == 3:
        if int(getattr(dataset, "NumberOfFrames", 1) or 1) > 1:
            raise UnsupportedScan("Multi-frame DICOM is not supported; export single slices.")
        image = image[..., 0]
    return image


def to_uint8(image: np.ndarray, photometric: str = "") -> np.ndarray:
    """Percentile (1-99) window to 0-255. Raw MR values often exceed 255 (12-16 bit)."""
    values = np.asarray(image, dtype=np.float32)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(finite, (1, 99))
    scaled = np.clip((values - low) / max(float(high - low), 1e-6), 0, 1)
    if str(photometric).upper() == "MONOCHROME1":
        scaled = 1.0 - scaled
    return np.round(np.nan_to_num(scaled) * 255).astype(np.uint8)
