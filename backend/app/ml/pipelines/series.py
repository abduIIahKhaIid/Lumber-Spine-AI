"""Series (ZIP) pipeline: Stage 1 3D localisation -> Stage 2 x/y refinement -> Stage 3 grading."""

from __future__ import annotations

import zipfile
from collections import Counter
from io import BytesIO
from pathlib import PurePosixPath

import numpy as np
import torch
from torchvision.transforms import v2

from app.ml import dicom
from app.ml.pipelines.common import (
    Progress,
    assemble,
    classify_crop,
    finding,
    image_entry,
    noop_progress,
    sort_findings,
)
from app.ml.preprocessing import (
    bounded_slice,
    neighboring_slices,
    preprocess_2p5d_crop,
    scs_nfn_normalize,
    severity_crop,
    severity_tensor,
    stage_normalize,
)
from app.ml.provenance import provenance
from app.ml.quality import assess_series
from app.ml.registry import device, get_registry
from app.ml.render import point_box

MAX_FILES = 1000
MAX_EXPANDED_BYTES = 700 * 1024 * 1024
JUNK = {"dicomdir", ".ds_store", "thumbs.db", "desktop.ini"}
EXPECTED_2P5D_NORMALIZATION = "2p5d_before_center_after_p1_p99_uint8_imagenet_mean_std"


def _read_archive(data: bytes) -> tuple[list[tuple[str, object]], int]:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise dicom.UnsupportedScan("The upload is not a valid ZIP archive.") from exc
    entries = [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and not info.filename.startswith("__MACOSX/")
        and PurePosixPath(info.filename).name.lower() not in JUNK
    ]
    if not entries:
        raise dicom.UnsupportedScan("The ZIP archive contains no files.")
    if len(entries) > MAX_FILES or sum(i.file_size for i in entries) > MAX_EXPANDED_BYTES:
        raise dicom.UnsupportedScan("The ZIP archive is too large. Upload one series at a time.")
    datasets, skipped = [], 0
    for info in entries:
        try:
            dataset = dicom.read_dataset(archive.read(info), force=True)
        except dicom.UnsupportedScan:
            skipped += 1
            continue
        if "PixelData" not in dataset or "ImagePositionPatient" not in dataset:
            skipped += 1
            continue
        datasets.append((info.filename, dataset))
    if not datasets:
        raise dicom.UnsupportedScan("No DICOM images with position information were found.")
    return datasets, skipped


def _series_condition(datasets) -> dict:
    """One supported classification for the whole archive (unknown slices inherit it)."""
    labels = Counter()
    for _name, dataset in datasets:
        info = dicom.classify(dataset)
        if info["condition"] != "Unknown":
            labels[(info["condition"], info["plane"], info["sequence"])] += 1
    if not labels:
        return dicom.classify(datasets[0][1])
    conditions = {condition for condition, _plane, _seq in labels}
    if len(conditions) > 1:
        raise dicom.UnsupportedScan(
            "The archive mixes series for different conditions. Upload one series per ZIP "
            "(sagittal T1, sagittal T2/STIR or axial T2)."
        )
    condition, plane, sequence = labels.most_common(1)[0][0]
    return {"condition": condition, "plane": plane, "sequence": sequence}


def run_series(data: bytes, progress: Progress = noop_progress) -> dict:
    progress(5, "Reading DICOM archive")
    datasets, skipped = _read_archive(data)
    lumbar_named = True
    for _name, dataset in datasets:
        lumbar_named = dicom.lumbar_status(dataset) and lumbar_named
    info = _series_condition(datasets)
    condition = dicom.require_supported(info)

    records, raw_images = [], []
    for index, (name, dataset) in enumerate(datasets):
        position = [float(v) for v in dataset.ImagePositionPatient]
        try:
            instance = int(getattr(dataset, "InstanceNumber", index + 1))
        except (TypeError, ValueError):
            instance = index + 1
        records.append(
            {
                "name": name,
                "position": position,
                "orientation": [
                    round(float(v), 4) for v in getattr(dataset, "ImageOrientationPatient", [])
                ],
                "pixel_spacing": [round(float(v), 4) for v in getattr(dataset, "PixelSpacing", [])],
                "instance_number": instance,
                "series_uid": str(getattr(dataset, "SeriesInstanceUID", "series")),
                "photometric": str(getattr(dataset, "PhotometricInterpretation", "")),
            }
        )
        raw_images.append(dicom.pixels(dataset))
        dicom.deidentify(dataset)

    # Sagittal series are ordered left-right (x); axial series head-feet (z).
    axis = 2 if condition == "SS" else 0
    order = sorted(range(len(records)), key=lambda i: records[i]["position"][axis])
    records = [records[i] for i in order]
    images = [raw_images[i] for i in order]
    shapes = {image.shape for image in images}
    if len(shapes) > 1:
        raise dicom.UnsupportedScan("Slices in this series have different image dimensions.")
    height, width = images[0].shape
    total = len(images)

    quality = assess_series(images, records)
    if skipped:
        quality["status"] = "review"
        quality["issues"].append(f"{skipped} non-image or unreadable file(s) were ignored.")
    if not lumbar_named:
        quality.setdefault("notes", []).append(
            "Lumbar anatomy is not named in the DICOM metadata; confirm the series manually."
        )

    registry = get_registry()
    dev = device()

    # ---------------- Stage 1: 3D localisation (x, y, z per level) -----------------------
    progress(20, "Stage 1: locating spinal levels in 3D")
    depth, size = (96, (256, 256)) if condition == "SS" else (32, (384, 384))
    stage1, meta1 = registry.stage1(condition)
    if meta1["architecture"] == "MedicalNetResNet10XYZ":
        if meta1.get("condition") != condition.lower() or meta1.get("input_depth") != depth:
            raise dicom.UnsupportedScan("Stage 1 checkpoint does not match this condition.")
        size = tuple(meta1["input_size"])
    resize1 = v2.Resize(size, antialias=True)
    volume = torch.cat(
        [resize1(torch.from_numpy(image.astype(np.float32))[None]) for image in images]
    )
    volume = stage_normalize(volume)
    if volume.shape[0] < depth:
        pad = torch.zeros(depth - volume.shape[0], *volume.shape[1:])
        volume = torch.cat([volume, pad])
    else:
        volume = torch.nn.functional.interpolate(volume[None, None], (depth, *size)).squeeze()
    with torch.inference_mode():
        stage1_out = stage1(volume.unsqueeze(0).to(dev))

    located: dict[str, dict] = {}
    boundary: set[str] = set()
    for level, xyz in stage1_out.items():
        x, y, z = xyz.squeeze(0).tolist()
        z_index = z * (depth if total < depth else total)
        slice_index = bounded_slice(z_index, total)
        if slice_index != int(z_index):
            boundary.add(level)
        located[level] = {"x": x * width, "y": y * height, "z": slice_index}
    if boundary:
        quality["status"] = "review"
        quality["issues"].append(
            "Some levels were localised outside the acquired slices; the nearest slice was used."
        )

    # ---------------- Stage 2: in-plane refinement ----------------------------------------
    progress(45, "Stage 2: refining level positions")
    resize2 = v2.Resize(size, antialias=True)
    stage2, meta2 = registry.stage2(condition)

    def prepared(index: int, normalizer) -> torch.Tensor:
        return resize2(torch.from_numpy(normalizer(images[index]).astype(np.float32))[None])

    if condition == "SS":
        stack = [
            stage_normalize(resize2(torch.from_numpy(images[item["z"]].astype(np.float32))[None]))
            for item in located.values()
        ]
        stage2_input = torch.stack(stack).unsqueeze(0)
    elif condition == "NFN":
        sides = []
        for side in ("right", "left"):  # model convention: index 0 = right image stack
            zs = [v["z"] for k, v in located.items() if k.startswith(side)]
            before, center, after = neighboring_slices(float(np.median(zs)), total)
            sides.append(
                torch.cat([prepared(i, scs_nfn_normalize) for i in (before, center, after)])
            )
        stage2_input = torch.stack(sides).unsqueeze(0)
        if meta2.get("input_side_order") == ["left", "right"]:
            stage2_input = stage2_input[:, [1, 0]]
        if meta2.get("input_channel_order") == ["center", "before", "after"]:
            stage2_input = stage2_input[:, :, [1, 0, 2]]
    else:
        zs = [v["z"] for v in located.values()]
        before, center, after = neighboring_slices(float(np.median(zs)), total)
        stage2_input = torch.cat(
            [prepared(i, scs_nfn_normalize) for i in (before, center, after)]
        ).unsqueeze(0)
    with torch.inference_mode():
        stage2_out = stage2(stage2_input.float().contiguous().to(dev))
    for level, xy in stage2_out.items():
        x, y = xy.squeeze(0).tolist()[:2]
        located[level]["x"], located[level]["y"] = x * width, y * height

    # ---------------- Stage 3: severity per level -----------------------------------------
    severity = registry.severity(condition)
    two_and_half = severity.input_slices == "before_center_after"
    if two_and_half and severity.checkpoint.get("normalization") != EXPECTED_2P5D_NORMALIZATION:
        raise dicom.UnsupportedScan("Severity checkpoint normalisation does not match.")
    if severity.input_slices not in (None, "center", "before_center_after"):
        raise dicom.UnsupportedScan("Unsupported severity checkpoint input format.")

    u8_cache: dict[int, np.ndarray] = {}

    def u8(index: int) -> np.ndarray:
        if index not in u8_cache:
            u8_cache[index] = dicom.to_uint8(images[index], records[index]["photometric"])
        return u8_cache[index]

    used_slices = sorted({item["z"] for item in located.values()})
    image_index = {z: i for i, z in enumerate(used_slices)}
    findings = []
    for number, (level, item) in enumerate(located.items(), start=1):
        progress(
            55 + int(35 * number / len(located)), f"Stage 3: grading {level.replace('_', ' ')}"
        )
        x, y, z = item["x"], item["y"], item["z"]
        crop = severity_crop(u8(z), x, y)
        if two_and_half:
            tensor = preprocess_2p5d_crop(
                images,
                records,
                z,
                x,
                y,
                severity.checkpoint["crop"],
                severity.checkpoint["image_size"],
            )
        else:
            tensor = severity_tensor(crop)
        scored = classify_crop(severity, tensor.to(dev), crop)
        reasons = (
            ["Localisation fell outside the acquired slices; verify this level manually."]
            if level in boundary
            else None
        )
        findings.append(
            finding(
                index=number,
                condition=condition,
                label=level,
                box=point_box(x, y, width, height),
                point=[x, y],
                image_index=image_index[z],
                slice_number=z + 1,
                scored=scored,
                severity=severity,
                localization=None,
                extra_reasons=reasons,
            )
        )
    sort_findings(findings)

    progress(93, "Rendering annotated slices")
    rendered = [image_entry(i, u8(z), findings, z + 1) for i, z in enumerate(used_slices)]
    first = records[0]
    acquisition = {
        "condition": condition,
        "plane": info["plane"],
        "sequence": info["sequence"],
        "dimensions": [int(height), int(width)],
        "pixel_spacing": first["pixel_spacing"],
        "slice_count": total,
    }
    result = assemble(
        mode="multi",
        info=info,
        findings=findings,
        images=rendered,
        quality=quality,
        provenance=provenance(condition, "multi", acquisition),
    )
    result["slice_count"] = total
    return result
