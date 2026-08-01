from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterator, Mapping, Optional, Sequence, Tuple
import unicodedata
from zipfile import ZIP_DEFLATED, ZipFile


EARTH_RADIUS_M = 6_378_137.0
PDF_FRAME_WIDTH_MM = 186.0
PDF_FRAME_HEIGHT_MM = 253.0
SUPPORTED_FORMATS = frozenset({"dxf", "dwg", "pdf"})
SUPPORTED_PDF_SCALES = frozenset({100, 1000})


class ExportUnavailableError(RuntimeError):
    """Raised when a required optional export backend is unavailable."""


@dataclass(frozen=True)
class ExportArtifact:
    content: bytes
    content_type: str
    filename: str


def _safe_filename(value: str, default: str = "dataset") -> str:
    normalized = unicodedata.normalize("NFKD", str(value or default))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_value).strip("._-")
    return (cleaned or default)[:96]


def _safe_layer_name(value: str) -> str:
    return _safe_filename(value, "DATASET").upper()[:64]


def _point(value: Any) -> Optional[Tuple[float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x_value = float(value[0])
        y_value = float(value[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x_value) or not math.isfinite(y_value):
        return None
    return x_value, y_value


def _points(values: Any) -> list[Tuple[float, float]]:
    if not isinstance(values, (list, tuple)):
        return []
    return [point for item in values if (point := _point(item)) is not None]


def _iter_geometry_parts(
    geometry: Any,
) -> Iterator[Tuple[str, list[Tuple[float, float]], bool]]:
    if not isinstance(geometry, Mapping):
        return
    geometry_type = str(geometry.get("type", "")).lower()
    coordinates = geometry.get("coordinates")

    if geometry_type == "point":
        point = _point(coordinates)
        if point is not None:
            yield "point", [point], False
    elif geometry_type == "multipoint":
        for point in _points(coordinates):
            yield "point", [point], False
    elif geometry_type == "linestring":
        line = _points(coordinates)
        if len(line) >= 2:
            yield "line", line, False
    elif geometry_type == "multilinestring" and isinstance(coordinates, (list, tuple)):
        for raw_line in coordinates:
            line = _points(raw_line)
            if len(line) >= 2:
                yield "line", line, False
    elif geometry_type == "polygon" and isinstance(coordinates, (list, tuple)):
        for raw_ring in coordinates:
            ring = _points(raw_ring)
            if len(ring) >= 3:
                yield "polygon", ring, True
    elif geometry_type == "multipolygon" and isinstance(coordinates, (list, tuple)):
        for raw_polygon in coordinates:
            if not isinstance(raw_polygon, (list, tuple)):
                continue
            for raw_ring in raw_polygon:
                ring = _points(raw_ring)
                if len(ring) >= 3:
                    yield "polygon", ring, True
    elif geometry_type == "geometrycollection":
        for child in geometry.get("geometries", []):
            yield from _iter_geometry_parts(child)


def _iter_payload_parts(
    payload: Mapping[str, Any],
) -> Iterator[Tuple[str, list[Tuple[float, float]], bool]]:
    if str(payload.get("type", "")).lower() == "feature":
        yield from _iter_geometry_parts(payload.get("geometry"))
        return
    for feature in payload.get("features", []):
        if isinstance(feature, Mapping):
            yield from _iter_geometry_parts(feature.get("geometry"))


def _local_xy(lon: float, lat: float, center: Tuple[float, float]) -> Tuple[float, float]:
    center_lon, center_lat = center
    lat_factor = max(1e-9, math.cos(math.radians(center_lat)))
    x_value = math.radians(lon - center_lon) * EARTH_RADIUS_M * lat_factor
    y_value = math.radians(lat - center_lat) * EARTH_RADIUS_M
    return x_value, y_value


def _dxf_pair(code: int, value: Any) -> str:
    return f"{code}\n{value}\n"


def _build_dxf(
    payload: Mapping[str, Any],
    *,
    layer_name: str,
    center: Tuple[float, float],
) -> bytes:
    layer = _safe_layer_name(layer_name)
    chunks = [
        _dxf_pair(0, "SECTION"), _dxf_pair(2, "HEADER"),
        _dxf_pair(9, "$ACADVER"), _dxf_pair(1, "AC1009"),
        _dxf_pair(9, "$INSUNITS"), _dxf_pair(70, 6),
        _dxf_pair(0, "ENDSEC"),
        _dxf_pair(0, "SECTION"), _dxf_pair(2, "TABLES"),
        _dxf_pair(0, "TABLE"), _dxf_pair(2, "LAYER"), _dxf_pair(70, 1),
        _dxf_pair(0, "LAYER"), _dxf_pair(2, layer), _dxf_pair(70, 0),
        _dxf_pair(62, 7), _dxf_pair(6, "CONTINUOUS"),
        _dxf_pair(0, "ENDTAB"), _dxf_pair(0, "ENDSEC"),
        _dxf_pair(0, "SECTION"), _dxf_pair(2, "ENTITIES"),
    ]

    for kind, coordinates, closed in _iter_payload_parts(payload):
        local_points = [_local_xy(lon, lat, center) for lon, lat in coordinates]
        if kind == "point":
            x_value, y_value = local_points[0]
            chunks.extend([
                _dxf_pair(0, "POINT"), _dxf_pair(8, layer),
                _dxf_pair(10, format(x_value, ".6f")),
                _dxf_pair(20, format(y_value, ".6f")), _dxf_pair(30, "0.0"),
            ])
            continue

        chunks.extend([
            _dxf_pair(0, "POLYLINE"), _dxf_pair(8, layer),
            _dxf_pair(66, 1), _dxf_pair(70, 1 if closed else 0),
        ])
        for x_value, y_value in local_points:
            chunks.extend([
                _dxf_pair(0, "VERTEX"), _dxf_pair(8, layer),
                _dxf_pair(10, format(x_value, ".6f")),
                _dxf_pair(20, format(y_value, ".6f")), _dxf_pair(30, "0.0"),
            ])
        chunks.extend([_dxf_pair(0, "SEQEND"), _dxf_pair(8, layer)])

    chunks.extend([_dxf_pair(0, "ENDSEC"), _dxf_pair(0, "EOF")])
    return "".join(chunks).encode("ascii", errors="strict")


def _resolve_converter(command: str) -> Optional[str]:
    raw_command = str(command or "").strip()
    if not raw_command:
        return None
    candidate = Path(raw_command)
    if candidate.is_file():
        return str(candidate)
    return shutil.which(raw_command)


def _convert_dxf_to_dwg(dxf_bytes: bytes, converter_command: str) -> bytes:
    executable = _resolve_converter(converter_command)
    if not executable:
        raise ExportUnavailableError(
            "DWG export requires LibreDWG dxf2dwg. Configure OPENLAYER_DWG_CONVERTER."
        )

    with tempfile.TemporaryDirectory(prefix="openlayer-dwg-") as temp_directory:
        input_path = Path(temp_directory) / "viewport.dxf"
        output_path = Path(temp_directory) / "viewport.dwg"
        input_path.write_bytes(dxf_bytes)
        process = subprocess.run(
            [executable, "--as", "r2000", "-o", str(output_path), str(input_path)],
            cwd=temp_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=45,
        )
        if process.returncode != 0 or not output_path.is_file():
            detail = process.stderr.decode("utf-8", errors="replace")[:400]
            raise ExportUnavailableError(f"DWG converter failed: {detail or process.returncode}")
        content = output_path.read_bytes()
        if len(content) < 32 or not content.startswith(b"AC10"):
            raise ExportUnavailableError("DWG converter returned an invalid DWG file.")
        return content


def pdf_bbox_for_scale(
    center: Sequence[float],
    scale: int,
) -> Tuple[float, float, float, float]:
    if scale not in SUPPORTED_PDF_SCALES:
        raise ValueError("PDF scale must be 100 or 1000")
    if len(center) != 2:
        raise ValueError("center must contain longitude and latitude")
    center_lon, center_lat = float(center[0]), float(center[1])
    if not math.isfinite(center_lon) or not math.isfinite(center_lat):
        raise ValueError("center contains invalid coordinates")

    half_width_m = PDF_FRAME_WIDTH_MM * scale / 2000.0
    half_height_m = PDF_FRAME_HEIGHT_MM * scale / 2000.0
    lat_factor = max(1e-9, math.cos(math.radians(center_lat)))
    lon_delta = math.degrees(half_width_m / (EARTH_RADIUS_M * lat_factor))
    lat_delta = math.degrees(half_height_m / EARTH_RADIUS_M)
    return (
        max(-180.0, center_lon - lon_delta),
        max(-90.0, center_lat - lat_delta),
        min(180.0, center_lon + lon_delta),
        min(90.0, center_lat + lat_delta),
    )


def _build_pdf(
    payload: Mapping[str, Any],
    *,
    dataset_title: str,
    center: Tuple[float, float],
    scale: int,
) -> bytes:
    try:
        from reportlab.lib.colors import Color, HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except Exception as exc:  # pragma: no cover - dependency checked in container build
        raise ExportUnavailableError("PDF export requires reportlab.") from exc

    output = BytesIO()
    page_width, page_height = A4
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle(f"{dataset_title} - 1:{scale}")
    pdf.setAuthor("VECTOPLAN OpenLayer")

    frame_left = 12 * mm
    frame_bottom = 18 * mm
    frame_width = PDF_FRAME_WIDTH_MM * mm
    frame_height = PDF_FRAME_HEIGHT_MM * mm
    points_per_meter = mm * 1000.0 / scale

    pdf.setFillColor(HexColor("#102632"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(frame_left, page_height - 10 * mm, str(dataset_title)[:88])
    pdf.setFont("Helvetica", 8)
    feature_count = len(payload.get("features", [])) if isinstance(payload.get("features"), list) else 0
    pdf.drawRightString(
        page_width - 12 * mm,
        page_height - 10 * mm,
        f"A4 | Massstab 1:{scale} | {feature_count} Features",
    )

    pdf.setStrokeColor(HexColor("#9fb2bb"))
    pdf.setLineWidth(0.4)
    pdf.rect(frame_left, frame_bottom, frame_width, frame_height, stroke=1, fill=0)

    clip_path = pdf.beginPath()
    clip_path.rect(frame_left, frame_bottom, frame_width, frame_height)
    pdf.saveState()
    pdf.clipPath(clip_path, stroke=0, fill=0)
    pdf.setStrokeColor(HexColor("#0b7894"))
    pdf.setFillColor(Color(0.043, 0.471, 0.58, alpha=0.12))
    pdf.setLineWidth(0.55)

    for kind, coordinates, closed in _iter_payload_parts(payload):
        local_points = [_local_xy(lon, lat, center) for lon, lat in coordinates]
        drawing_points = [
            (
                frame_left + frame_width / 2.0 + x_value * points_per_meter,
                frame_bottom + frame_height / 2.0 + y_value * points_per_meter,
            )
            for x_value, y_value in local_points
        ]
        if kind == "point":
            x_value, y_value = drawing_points[0]
            pdf.circle(x_value, y_value, 1.1 * mm, stroke=1, fill=1)
            continue
        path = pdf.beginPath()
        path.moveTo(*drawing_points[0])
        for point in drawing_points[1:]:
            path.lineTo(*point)
        if closed:
            path.close()
        pdf.drawPath(path, stroke=1, fill=1 if kind == "polygon" else 0)

    pdf.restoreState()
    pdf.setStrokeColor(HexColor("#102632"))
    pdf.setFillColor(HexColor("#102632"))
    north_x = frame_left + frame_width - 8 * mm
    north_y = frame_bottom + frame_height - 14 * mm
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawCentredString(north_x, north_y + 8 * mm, "N")
    pdf.line(north_x, north_y, north_x, north_y + 6 * mm)
    pdf.line(north_x, north_y + 6 * mm, north_x - 1.5 * mm, north_y + 3.5 * mm)
    pdf.line(north_x, north_y + 6 * mm, north_x + 1.5 * mm, north_y + 3.5 * mm)

    pdf.setFont("Helvetica", 7)
    pdf.drawString(
        frame_left,
        8 * mm,
        f"Zentrum WGS84: {center[0]:.7f}, {center[1]:.7f} | Nur ausgewaehlter Datensatz",
    )
    pdf.drawRightString(page_width - 12 * mm, 8 * mm, "VECTOPLAN")
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def build_export_artifact(
    *,
    export_format: str,
    dataset_id: str,
    dataset_title: str,
    payload: Mapping[str, Any],
    center: Sequence[float],
    scale: Optional[int] = None,
    dwg_converter_command: str = "dxf2dwg",
) -> ExportArtifact:
    normalized_format = str(export_format or "").strip().lower()
    if normalized_format not in SUPPORTED_FORMATS:
        raise ValueError("format must be dxf, dwg or pdf")
    if len(center) != 2:
        raise ValueError("center must contain longitude and latitude")
    normalized_center = float(center[0]), float(center[1])
    base_name = _safe_filename(dataset_title or dataset_id, "dataset")
    coordinate_name = f"{normalized_center[1]:.6f}_{normalized_center[0]:.6f}".replace("-", "m")

    if normalized_format == "pdf":
        normalized_scale = int(scale or 0)
        if normalized_scale not in SUPPORTED_PDF_SCALES:
            raise ValueError("PDF scale must be 100 or 1000")
        content = _build_pdf(
            payload,
            dataset_title=dataset_title or dataset_id,
            center=normalized_center,
            scale=normalized_scale,
        )
        return ExportArtifact(
            content=content,
            content_type="application/pdf",
            filename=f"{base_name}_{coordinate_name}_M{normalized_scale}.pdf",
        )

    dxf_content = _build_dxf(
        payload,
        layer_name=dataset_title or dataset_id,
        center=normalized_center,
    )
    if normalized_format == "dxf":
        return ExportArtifact(
            content=dxf_content,
            content_type="application/dxf",
            filename=f"{base_name}_{coordinate_name}.dxf",
        )

    return ExportArtifact(
        content=_convert_dxf_to_dwg(dxf_content, dwg_converter_command),
        content_type="application/acad",
        filename=f"{base_name}_{coordinate_name}.dwg",
    )


def build_pdf_zip_artifact(
    *,
    dataset_id: str,
    dataset_title: str,
    payloads_by_scale: Mapping[int, Mapping[str, Any]],
    center: Sequence[float],
) -> ExportArtifact:
    """Packages the two supported A4 PDF scales into one ZIP download."""
    if len(center) != 2:
        raise ValueError("center must contain longitude and latitude")

    missing_scales = sorted(
        scale for scale in SUPPORTED_PDF_SCALES if scale not in payloads_by_scale
    )
    if missing_scales:
        raise ValueError(
            "PDF ZIP requires payloads for scales: "
            + ", ".join(str(scale) for scale in missing_scales)
        )

    normalized_center = float(center[0]), float(center[1])
    base_name = _safe_filename(dataset_title or dataset_id, "dataset")
    coordinate_name = (
        f"{normalized_center[1]:.6f}_{normalized_center[0]:.6f}".replace("-", "m")
    )
    output = BytesIO()

    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        for scale in sorted(SUPPORTED_PDF_SCALES):
            artifact = build_export_artifact(
                export_format="pdf",
                dataset_id=dataset_id,
                dataset_title=dataset_title,
                payload=payloads_by_scale[scale],
                center=normalized_center,
                scale=scale,
            )
            archive.writestr(artifact.filename, artifact.content)

    return ExportArtifact(
        content=output.getvalue(),
        content_type="application/zip",
        filename=f"{base_name}_{coordinate_name}_PDF_A4.zip",
    )
