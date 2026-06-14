"""Validation a posteriori d'une solution exportee.

Ce script ne depend pas du solveur. Il relit les decisions CSV et controle :
- unicite des commandes,
- respect des routages, dont la contrainte epaisseur LGA/LGB,
- capacites nettes par ligne/famille/semaine,
- disponibilite HRC par grade,
- bornes de stocks.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_loader import load_data
from src.model import allowed_routes, capacity_value


TOL = 1e-4


def validate(data_path: Path, decisions_path: Path) -> pd.DataFrame:
    data = load_data(data_path)
    decisions = pd.read_csv(decisions_path)
    issues: list[dict[str, object]] = []

    if decisions.empty:
        issues.append({"check": "non_empty", "status": "FAIL", "detail": "Aucune decision exportee"})
        return pd.DataFrame(issues)

    counts = decisions.groupby("order_id")["value"].sum()
    for order_id, value in counts[counts > 1 + TOL].items():
        issues.append({"check": "order_once", "status": "FAIL", "detail": f"{order_id}: somme={value}"})

    orders = data.orders.set_index("ID")
    for _, row in decisions.iterrows():
        order = orders.loc[row["order_id"]]
        allowed = {r.id for r in allowed_routes(order)}
        if row["route_id"] not in allowed:
            issues.append(
                {
                    "check": "routing",
                    "status": "FAIL",
                    "detail": f"{row['order_id']}: route {row['route_id']} non admissible",
                }
            )
        thickness = float(order["Epaisseur"])
        lines = str(row["route_lines"]).split(">")
        if thickness < 0.6 and "LGB" in lines:
            issues.append({"check": "thickness", "status": "FAIL", "detail": f"{row['order_id']}: <0.6 sur LGB"})
        if thickness > 0.6 and "LGA" in lines:
            issues.append({"check": "thickness", "status": "FAIL", "detail": f"{row['order_id']}: >0.6 sur LGA"})

    capacity = pd.read_csv(decisions_path.parent / decisions_path.name.replace("_decisions", "_capacity"))
    for _, row in capacity.iterrows():
        if row["used_t"] > row["capacity_t"] + TOL:
            issues.append(
                {
                    "check": "capacity",
                    "status": "FAIL",
                    "detail": f"{row['line']}/{row['family']}/S{row['week']}: {row['used_t']} > {row['capacity_t']}",
                }
            )
        recomputed_cap = capacity_value(data, row["line"], row["family"], int(row["week"]))
        if recomputed_cap is not None and abs(recomputed_cap - row["capacity_t"]) > TOL:
            issues.append(
                {
                    "check": "capacity_formula",
                    "status": "FAIL",
                    "detail": f"{row['line']}/{row['family']}/S{row['week']}: capacite export incoherente",
                }
            )

    hrc = pd.read_csv(decisions_path.parent / decisions_path.name.replace("_decisions", "_hrc"))
    for _, row in hrc.iterrows():
        if row["used_t"] > row["available_t"] + TOL:
            issues.append({"check": "hrc", "status": "FAIL", "detail": f"{row['grade']}: HRC depasse"})

    stocks = pd.read_csv(decisions_path.parent / decisions_path.name.replace("_decisions", "_stocks"))
    for _, row in stocks.iterrows():
        if not bool(row["within_bounds"]):
            issues.append(
                {
                    "check": "stocks",
                    "status": "FAIL",
                    "detail": f"{row['family_or_point']}/S{row['week']}: hors bornes",
                }
            )

    if not issues:
        issues.append({"check": "all", "status": "OK", "detail": "Toutes les contraintes controlees sont respectees"})
    return pd.DataFrame(issues)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="Donnees_MaghrebSteel.xlsx")
    parser.add_argument("--decisions", default="outputs/base_decisions.csv")
    parser.add_argument("--out", default="outputs/validation_base.csv")
    args = parser.parse_args()

    report = validate(Path(args.data), Path(args.decisions))
    report.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(report.to_string(index=False))
    if (report["status"] == "FAIL").any():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
