import argparse
import json
from . import Repository, get_learning_dataset, get_site_kpis, get_retraining_readiness
from .seed import seed_demo


def main():
    parser = argparse.ArgumentParser(description="LastPlate synthetic DEMO; adds a fresh demo site per run")
    parser.add_argument("--db", help="SQLite path, overrides LASTPLATE_DB_PATH")
    args = parser.parse_args()
    with Repository(args.db) as repository:
        site = seed_demo(repository)
        print("DEMO - synthetic values, not measured results")
        for label in ("Created site", "Saved prediction", "Saved operation plan", "Saved actual result"):
            print(label)
        for label, value in (("Learning dataset (explicit DEMO opt-in)", get_learning_dataset(repository, site["site_id"], include_demo=True)),
                             ("KPI (safe eligible default)", get_site_kpis(repository, site["site_id"])),
                             ("KPI (DEMO, explicit legacy all-row)", get_site_kpis(repository, site["site_id"], eligible_only=False)),
                             ("Retraining readiness (safe eligible default)", get_retraining_readiness(repository, site["site_id"]))):
            print(label + ":")
            # ASCII JSON handles arbitrary text even on Windows CP949 stdout.
            print(json.dumps(value, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
