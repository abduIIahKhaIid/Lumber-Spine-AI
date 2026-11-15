import numpy as np
import pytest
from pydicom.dataset import Dataset, FileMetaDataset

from app.ml import dicom
from app.ml.preprocessing import bounded_slice, neighboring_slices, severity_crop


def scan(body_part="", modality="MR", description="SAG T2"):
    ds = Dataset()
    ds.Modality = modality
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.SeriesDescription = description
    ds.ImageOrientationPatient = [0, 1, 0, 0, 0, -1]
    if body_part:
        ds.BodyPartExamined = body_part
    return ds


def test_lumbar_named_and_unlabelled():
    assert dicom.lumbar_status(scan("LSPINE")) is True
    assert dicom.lumbar_status(scan()) is False


@pytest.mark.parametrize("bad", [scan("CSPINE"), scan("LSPINE", "CT"), scan("KNEE")])
def test_non_lumbar_or_non_mr_rejected(bad):
    with pytest.raises(dicom.UnsupportedScan):
        dicom.lumbar_status(bad)


def test_classification_matrix():
    assert dicom.classify(scan(description="Sagittal T2/STIR"))["condition"] == "SCS"
    assert dicom.classify(scan(description="Sagittal T1"))["condition"] == "NFN"
    axial = scan(description="Axial T2")
    axial.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    assert dicom.classify(axial)["condition"] == "SS"
    unknown = scan(description="localizer")
    with pytest.raises(dicom.UnsupportedScan):
        dicom.require_supported(dicom.classify(unknown))


def test_deidentify_removes_patient_and_private_tags():
    ds = scan()
    ds.PatientName = "Jane^Doe"
    ds.PatientID = "123"
    ds.InstitutionName = "Hospital"
    ds.add_new(0x00091001, "LO", "private")
    dicom.deidentify(ds)
    assert "PatientName" not in ds and "PatientID" not in ds
    assert "InstitutionName" not in ds
    assert (0x0009, 0x1001) not in ds
    assert ds.SeriesDescription == "SAG T2"


def test_to_uint8_windows_16_bit_values_instead_of_clipping():
    raw = np.linspace(0, 1500, 64 * 64, dtype=np.float32).reshape(64, 64).astype(np.uint16)
    image = dicom.to_uint8(raw)
    assert image.dtype == np.uint8
    # The old Image.fromarray(uint16).convert("RGB") path saturated ~80% of this ramp.
    assert (image == 255).mean() < 0.05
    assert image.min() == 0 and image.max() == 255
    inverted = dicom.to_uint8(raw, "MONOCHROME1")
    assert inverted[0, 0] == 255


def test_slice_bounds_never_wrap():
    assert bounded_slice(-1, 10) == 0
    assert bounded_slice(42, 10) == 9
    assert neighboring_slices(0, 10) == (0, 0, 1)
    with pytest.raises(ValueError):
        bounded_slice(float("nan"), 10)


def test_severity_crop_is_rgb_and_handles_edges():
    crop = severity_crop(np.zeros((64, 64), dtype=np.uint8), 2, 2)
    assert crop.mode == "RGB" and crop.size[0] > 0
