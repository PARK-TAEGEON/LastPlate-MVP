"""Extract the supplied native LightGBM text without executing pickle opcodes.

Usage: python scripts/import_ml_bundle.py path/to/LastPlate-ML-v2.zip
The original archive is never changed. Only the selected release is imported.
"""
import argparse
import hashlib
import json
import pickletools
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "backend" / "ml_bundle"
    prefix = "lastplate-ml-v2/"
    with zipfile.ZipFile(args.archive) as archive:
        pointer = json.loads(archive.read(prefix + "models/current.json"))
        version = pointer["model_version"]
        if not version or any(c in version for c in ("/", "\\", ":")) or version in (".", ".."):
            raise ValueError("Invalid release ID")
        release = prefix + "models/releases/" + version + "/"
        metadata = json.loads(archive.read(release + "metadata.json"))
        artifact = archive.read(release + "demand_model.pkl")
        if hashlib.sha256(artifact).hexdigest() != metadata["model_sha256"]:
            raise ValueError("Original model checksum mismatch")
        models = [arg for _, arg, _ in pickletools.genops(artifact)
                  if isinstance(arg, str) and arg.startswith("tree\nversion=")]
        if len(models) != 1 or metadata["feature_group"] != "C":
            raise ValueError("Expected one LightGBM group C native model")
        native = models[0].encode("utf-8")
        metadata.update(native_sha256=hashlib.sha256(native).hexdigest(),
                        feature_rules_version="v1", interval_method="point_only",
                        import_method="pickletools string extraction; no unpickling; no retraining")
        profile = json.loads(archive.read(prefix + "reports/data_profile.json"))
        metadata["estimated_available_training_range"] = [profile["estimated_available_min"], profile["estimated_available_max"]]
        output.mkdir(parents=True, exist_ok=True)
        (output / "demand_model.txt").write_bytes(native)
        (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "inference_smoke.json").write_bytes(archive.read(prefix + "reports/inference_smoke.json"))
        # Preserve the exact preprocessing reference for this release.
        (output / "feature_rules_reference.txt").write_bytes(archive.read(prefix + "ml/config.py"))
    print(f"Imported {version}: {len(native)} bytes -> {output}")


if __name__ == "__main__":
    main()
