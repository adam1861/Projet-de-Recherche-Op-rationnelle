"""Point d'entree du projet Maghreb Steel.

Lance le modele PuLP, les scenarios demandes et les exports CSV/Excel.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.data_loader import load_data
from src.model import build_options, build_refused_report, export_result, parse_cbc_nodes, solve_model


def run_all(data_path: Path, out_dir: Path, time_limit: int = 300) -> None:
    """Run base case, LP relaxation, sensitivity scenarios and bonus analyses."""

    out_dir.mkdir(parents=True, exist_ok=True)
    data = load_data(data_path)

    base_log = out_dir / "cbc_base.log"
    base = solve_model(data, campaigns=False, relax=False, time_limit=time_limit, log_path=base_log)
    export_result(base, out_dir, "base")

    lp = solve_model(data, campaigns=False, relax=True, time_limit=time_limit)
    export_result(lp, out_dir, "relaxation_lp")
    base_refused_shadow = build_refused_report(base.orders, build_options(data), lp.shadows, lp.reduced_costs)
    base_refused_shadow.to_csv(out_dir / "base_refused_shadow_based.csv", index=False, encoding="utf-8-sig")

    campaign_log = out_dir / "cbc_campaigns.log"
    campaigns = solve_model(data, campaigns=True, relax=False, time_limit=time_limit, log_path=campaign_log, staged_routes=False)
    export_result(campaigns, out_dir, "campaigns")

    campaign_lp = solve_model(data, campaigns=True, relax=True, time_limit=time_limit, staged_routes=False)
    export_result(campaign_lp, out_dir, "campaigns_relaxation_lp")

    hrc10 = solve_model(data, hrc_multiplier=1.10, time_limit=time_limit)
    export_result(hrc10, out_dir, "scenario_hrc_plus_10")

    lgb_down = solve_model(data, extra_lgb_stop_week2=2.0, time_limit=time_limit)
    export_result(lgb_down, out_dir, "scenario_lgb_panne_s2")

    urgent_data = load_data(data_path)
    urgent = urgent_data.orders.copy()
    urgent.loc[len(urgent)] = {
        "ID": "URG-001",
        "Client": "Nouveau_Client",
        "Famille": "HDG",
        "Grade": "DC01",
        "Epaisseur": 0.5,
        "Largeur": 1140,
        "Tonnage": 300.0,
        "Prix": 11500.0,
        "DueWeek": 1,
        "Priorite": "Haute",
    }
    urgent_data = urgent_data.__class__(
        orders=urgent,
        cadences=urgent_data.cadences,
        yields=urgent_data.yields,
        scrap_rates=urgent_data.scrap_rates,
        downgraded_rates=urgent_data.downgraded_rates,
        nonconforming_rates=urgent_data.nonconforming_rates,
        costs=urgent_data.costs,
        hrc_prices=urgent_data.hrc_prices,
        hrc_availability=urgent_data.hrc_availability,
        finished_stocks=urgent_data.finished_stocks,
        interprocess_stocks=urgent_data.interprocess_stocks,
        pk_stocks=urgent_data.pk_stocks,
        stops=urgent_data.stops,
        params=urgent_data.params,
    )
    urgent_result = solve_model(urgent_data, time_limit=time_limit)
    export_result(urgent_result, out_dir, "scenario_commande_urgente")

    envelope_rows = []
    for mult in [0.50, 0.70, 0.90, 1.00, 1.10, 1.50]:
        res = solve_model(data, dc01_availability_multiplier=mult, time_limit=time_limit)
        envelope_rows.append(
            {
                "dc01_multiplier": mult,
                "dc01_available_t": data.hrc_availability["DC01"] * mult,
                "objective_mad": res.objective,
                "service_rate": res.orders.loc[res.orders["accepted"], "tonnage"].sum() / res.orders["tonnage"].sum(),
                "accepted_orders": int(res.orders["accepted"].sum()),
            }
        )
    envelope = pd.DataFrame(envelope_rows)
    envelope.to_csv(out_dir / "bonus_dc01_envelope.csv", index=False, encoding="utf-8-sig")

    robust_rows = []
    for mult in [0.95, 1.00, 1.05]:
        res = solve_model(data, cadence_multiplier=mult, time_limit=time_limit)
        robust_rows.append(
            {
                "cadence_multiplier": mult,
                "objective_mad": res.objective,
                "service_rate": res.orders.loc[res.orders["accepted"], "tonnage"].sum() / res.orders["tonnage"].sum(),
                "accepted_orders": int(res.orders["accepted"].sum()),
                "max_utilization": res.capacity["utilization"].max(),
            }
        )
    robustness = pd.DataFrame(robust_rows)
    robustness.to_csv(out_dir / "bonus_robustesse_cadences.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(
        [
            summarize("base", base, parse_cbc_nodes(base_log)),
            summarize("relaxation_lp", lp, None),
            summarize("campaigns", campaigns, parse_cbc_nodes(campaign_log)),
            summarize("campaigns_relaxation_lp", campaign_lp, None),
            summarize("hrc_plus_10", hrc10, None),
            summarize("lgb_panne_s2", lgb_down, None),
            summarize("commande_urgente", urgent_result, None),
        ]
    )
    summary.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out_dir / "synthese_scenarios.xlsx", engine="xlsxwriter") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        envelope.to_excel(writer, sheet_name="dc01_envelope", index=False)
        robustness.to_excel(writer, sheet_name="robustesse", index=False)


def summarize(name: str, result, nodes: int | None) -> dict[str, object]:
    total_tonnage = result.orders["tonnage"].sum()
    served_tonnage = result.orders.loc[result.orders["accepted"], "tonnage"].sum()
    urgent_accepted = False
    if "URG-001" in set(result.orders["order_id"]):
        urgent_accepted = bool(result.orders.loc[result.orders["order_id"] == "URG-001", "accepted"].iloc[0])
    return {
        "scenario": name,
        "status": result.status,
        "objective_mad": result.objective,
        "runtime_s": result.runtime_s,
        "variables": result.metadata["variables"],
        "constraints": result.metadata["constraints"],
        "accepted_orders": int(result.orders["accepted"].sum()),
        "refused_orders": int((~result.orders["accepted"]).sum()),
        "served_tonnage": served_tonnage,
        "total_tonnage": total_tonnage,
        "service_rate": served_tonnage / total_tonnage if total_tonnage else 0,
        "urgent_accepted": urgent_accepted,
        "cbc_nodes": nodes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="Donnees_MaghrebSteel.xlsx")
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--time-limit", type=int, default=300)
    args = parser.parse_args()
    run_all(Path(args.data), Path(args.out), args.time_limit)


if __name__ == "__main__":
    main()
