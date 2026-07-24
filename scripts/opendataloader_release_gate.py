"""Capture and fail-close verification for OpenDataLoader redistribution evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
NOTICE_PREFIX = "opendataloader_pdf/"
NOTICE_FILES = ("LICENSE", "NOTICE", "THIRD_PARTY/")


class GateError(ValueError):
    """An incomplete or unreconciled distribution input."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid JSON evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise GateError(f"JSON evidence must be an object: {path.name}")
    return value


def collect(args: argparse.Namespace) -> None:
    wheel = Path(args.wheel).resolve(strict=True)
    if wheel.suffix != ".whl":
        raise GateError("--wheel must reference the downloaded .whl artifact")
    if not REVISION_RE.fullmatch(args.source_revision):
        raise GateError("--source-revision must be an immutable 40-64 character Git revision")
    if not args.source_url or not all(
        url.startswith("https://") and args.source_revision in url for url in args.source_url
    ):
        raise GateError("at least one immutable https corresponding-source URL is required")

    notice_root = Path(args.notice_root).resolve()
    notice_root.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, str]] = []
    jars: list[dict[str, str]] = []

    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            if name.endswith("/") or not name.startswith(NOTICE_PREFIX):
                continue
            relative = name.removeprefix(NOTICE_PREFIX)
            if not relative.startswith(NOTICE_FILES):
                continue
            target = notice_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            copied.append({"path": target.relative_to(notice_root).as_posix(), "sha256": sha256_file(target)})

            if relative.endswith(".jar"):
                jars.append({"path": target.relative_to(notice_root).as_posix(), "sha256": sha256_file(target)})

    if not copied:
        raise GateError("wheel does not contain OpenDataLoader notice material")
    if not jars:
        # The bundled JAR is intentionally copied even though it is not notice text.
        with zipfile.ZipFile(wheel) as archive:
            jar_names = [item.filename for item in archive.infolist() if item.filename.endswith(".jar")]
            if len(jar_names) != 1:
                raise GateError("wheel must contain exactly one bundled JAR")
            target = notice_root / "jar" / Path(jar_names[0]).name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(jar_names[0]) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            jars.append({"path": target.relative_to(notice_root).as_posix(), "sha256": sha256_file(target)})

    manifest = {
        "schema_version": 1,
        "integration": "opendataloader-pdf",
        "version": "2.5.0",
        "source_revision": args.source_revision,
        "corresponding_source_urls": args.source_url,
        "wheel": {"filename": wheel.name, "sha256": sha256_file(wheel)},
        "bundled_jars": jars,
        "notices": copied,
    }
    write_json(Path(args.manifest), manifest)


def _component_values(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "name" in value and ("version" in value or "versionInfo" in value):
            yield value
        for child in value.values():
            yield from _component_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _component_values(child)


def _licenses(component: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("licenses", "licenseConcluded", "licenseDeclared"):
        value = component.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict):
                    license_value = item.get("license", item)
                    if isinstance(license_value, dict):
                        values.extend(str(v) for v in license_value.values() if isinstance(v, str))
    return values


def _validate_sbom(path: Path) -> None:
    sbom = read_json(path)
    components = list(_component_values(sbom))
    if not components:
        raise GateError(f"SBOM has no versioned components: {path.name}")
    for component in components:
        name = str(component.get("name", "")).strip()
        version = str(component.get("version", component.get("versionInfo", ""))).strip()
        licenses = _licenses(component)
        if not name or not version or version.upper() in {"UNKNOWN", "UNRESOLVED", "NOASSERTION"}:
            raise GateError(f"SBOM has unresolved component identity: {path.name}")
        if not licenses or any("NOASSERTION" in item.upper() for item in licenses):
            raise GateError(f"SBOM has unresolved license for {name}: {path.name}")


def verify(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest = read_json(manifest_path)
    if manifest.get("integration") != "opendataloader-pdf" or manifest.get("version") != "2.5.0":
        raise GateError("manifest is not for opendataloader-pdf 2.5.0")
    if not REVISION_RE.fullmatch(str(manifest.get("source_revision", ""))):
        raise GateError("manifest has no immutable source revision")
    if not manifest.get("corresponding_source_urls"):
        raise GateError("manifest has no corresponding-source reference")
    if not SHA256_RE.fullmatch(str(manifest.get("wheel", {}).get("sha256", ""))):
        raise GateError("manifest wheel hash is missing or invalid")
    jars = manifest.get("bundled_jars")
    notices = manifest.get("notices")
    if not isinstance(jars, list) or not jars or not isinstance(notices, list) or not notices:
        raise GateError("manifest is missing bundled JAR or notice inventory")
    if not args.image_digest.startswith("sha256:") or not SHA256_RE.fullmatch(args.image_digest.removeprefix("sha256:")):
        raise GateError("--image-digest must be the final OCI sha256 digest")

    notice_root = Path(args.notice_root).resolve(strict=True)
    for notice in notices:
        if not isinstance(notice, dict):
            raise GateError("manifest notice inventory is malformed")
        relative = notice.get("path")
        expected_hash = notice.get("sha256")
        if not isinstance(relative, str) or Path(relative).is_absolute() or not SHA256_RE.fullmatch(str(expected_hash)):
            raise GateError("manifest notice record is incomplete")
        target = (notice_root / relative).resolve()
        if notice_root not in target.parents or not target.is_file() or sha256_file(target) != expected_hash:
            raise GateError(f"missing or changed notice file: {relative}")

    for sbom in args.sbom:
        _validate_sbom(Path(sbom).resolve(strict=True))

    reconciliation = read_json(Path(args.reconciliation).resolve(strict=True))
    components = reconciliation.get("components")
    if not isinstance(components, list) or not components:
        raise GateError("reconciliation has no component records")
    for component in components:
        if not isinstance(component, dict) or component.get("disposition") != "approved":
            raise GateError("all version discrepancies, including veraPDF, require approval")
        if not component.get("actual_version") or not component.get("notice_version") or not component.get("owner"):
            raise GateError("reconciliation record is incomplete")

    approval = read_json(Path(args.approval).resolve(strict=True))
    if approval.get("integration") != "opendataloader-pdf" or approval.get("version") != "2.5.0":
        raise GateError("approval does not match OpenDataLoader 2.5.0")
    if approval.get("approved") is not True or not approval.get("license_owner") or not approval.get("approved_at"):
        raise GateError("written license-owner approval is required")
    if not SHA256_RE.fullmatch(str(approval.get("evidence_manifest_sha256", ""))):
        raise GateError("approval must bind to the evidence manifest hash")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)

    collect_parser = actions.add_parser("collect", help="extract evidence from a downloaded wheel")
    collect_parser.add_argument("--wheel", required=True)
    collect_parser.add_argument("--notice-root", required=True)
    collect_parser.add_argument("--manifest", required=True)
    collect_parser.add_argument("--source-revision", required=True)
    collect_parser.add_argument("--source-url", action="append", required=True)
    collect_parser.set_defaults(func=collect)

    verify_parser = actions.add_parser("verify", help="fail closed on incomplete release evidence")
    verify_parser.add_argument("--manifest", required=True)
    verify_parser.add_argument("--notice-root", required=True)
    verify_parser.add_argument("--sbom", action="append", required=True)
    verify_parser.add_argument("--reconciliation", required=True)
    verify_parser.add_argument("--approval", required=True)
    verify_parser.add_argument("--image-digest", required=True)
    verify_parser.set_defaults(func=verify)

    try:
        args = parser.parse_args()
        args.func(args)
    except (GateError, OSError, zipfile.BadZipFile) as exc:
        print(f"OpenDataLoader release gate failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
