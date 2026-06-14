"""Modele d'optimisation PuLP pour le simulateur Capacite-Commande."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
import time
from typing import Iterable

import pandas as pd
import pulp

from .data_loader import InputData, WEEKS, thickness_bucket


LINES = ["PK", "CRMA", "CRMB", "BAF", "SKP", "LGA", "LGB"]
MAIN_FAMILIES = ["CRC", "HDG", "PPGI", "BACR"]
MODELED_FAMILIES = ["HRC DEC", "CRC", "HDG", "PPGI", "BACR"]


@dataclass(frozen=True)
class Route:
    id: str
    family: str
    lines: tuple[str, ...]


@dataclass
class SolveResult:
    status: str
    objective: float
    runtime_s: float
    decisions: pd.DataFrame
    orders: pd.DataFrame
    capacity: pd.DataFrame
    stocks: pd.DataFrame
    hrc: pd.DataFrame
    shadows: pd.DataFrame
    reduced_costs: pd.DataFrame
    family_margins: pd.DataFrame
    refused: pd.DataFrame
    metadata: dict[str, float | str]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")


def allowed_routes(order: pd.Series) -> list[Route]:
    """Return all industrially admissible routes for one order."""

    family = str(order["Famille"])
    e = float(order["Epaisseur"])

    if family == "Quarto":
        return []
    if family == "HRC DEC":
        return [Route("HRCDEC_PK", family, ("PK",))]
    if family == "CRC":
        return [Route("CRC_CRMB_BAF_SKP", family, ("PK", "CRMB", "BAF", "SKP"))]

    # Contrainte ajoutee par image : <0.6 sur LGA, >0.6 strictement sur LGB.
    if e < 0.6:
        downstream = ["LGA"]
    elif e > 0.6:
        downstream = ["LGB"]
    else:
        downstream = []

    routes: list[Route] = []
    if family == "HDG":
        for crm in ["CRMA", "CRMB"]:
            for galva in downstream:
                routes.append(Route(f"HDG_{crm}_{galva}", family, ("PK", crm, galva)))
    elif family == "PPGI":
        # Regle projet : PPGI exclusivement par LGA. Si e > 0.6, la contrainte
        # additionnelle impose LGB et la commande devient non routable.
        if "LGA" in downstream:
            for crm in ["CRMA", "CRMB"]:
                routes.append(Route(f"PPGI_{crm}_LGA", family, ("PK", crm, "LGA")))
    elif family == "BACR":
        if "LGB" in downstream:
            routes.append(Route("BACR_A_CRMB_BAF_LGB", family, ("PK", "CRMB", "BAF", "LGB")))
        for crm in ["CRMA", "CRMB"]:
            for line in downstream:
                routes.append(Route(f"BACR_B_{crm}_{line}", family, ("PK", crm, line)))
    return routes


def process_cost_key(line: str, family: str) -> str:
    if line in {"LGA", "LGB"} and family in {"HDG", "PPGI", "BACR"}:
        return f"{line}-{family}"
    return line


def route_inputs(route: Route, final_tonnage: float, yields: dict[str, float]) -> dict[str, float]:
    """Tonnage processed at each route line to obtain final_tonnage at the end."""

    inputs: dict[str, float] = {}
    suffix_yield = 1.0
    for line in reversed(route.lines):
        suffix_yield *= yields[line]
        inputs[line] = final_tonnage / suffix_yield
    return inputs


def route_economics(order: pd.Series, route: Route, data: InputData) -> dict[str, float]:
    """Compute revenue, variable costs and unit resource use for one order-route."""

    tonnage = float(order["Tonnage"])
    price = float(order["Prix"])
    grade = str(order["Grade"])
    width = int(order["Largeur"])
    bucket = thickness_bucket(float(order["Epaisseur"]))
    inputs = route_inputs(route, tonnage, data.yields)

    revenue = tonnage * price
    transform_cost = 0.0
    scrap_value = 0.0
    downgraded_value = 0.0
    nonconforming_value = 0.0
    for line, processed in inputs.items():
        key = process_cost_key(line, route.family)
        transform_cost += processed * data.costs[key][bucket]
        scrap_value += processed * data.scrap_rates[line] * data.params["Prix de valorisation des chutes"]
        downgraded_value += processed * data.downgraded_rates[line] * data.params["Coefficient déclassé/conforme"] * price
        nonconforming_value += processed * data.nonconforming_rates[line] * data.params["Coefficient non-conforme/conforme"] * price

    hrc_input = tonnage / math.prod(data.yields[line] for line in route.lines)
    hrc_cost = hrc_input * data.hrc_prices[(grade, width)]

    zinc_cost = 0.0
    paint_cost = 0.0
    if route.family == "HDG":
        zinc_cost = tonnage * data.params["Consommation zinc HDG"] * data.params["Prix zinc"]
    if route.family == "PPGI":
        zinc_cost = tonnage * data.params["Consommation zinc PPGI"] * data.params["Prix zinc"]
    if route.family == "PPGI":
        paint_cost = tonnage * data.params["Consommation peinture PPGI"] * data.params["Prix peinture (PPGI)"]

    margin_before_timing = (
        revenue
        - transform_cost
        - hrc_cost
        - zinc_cost
        - paint_cost
        + scrap_value
        + downgraded_value
        + nonconforming_value
    )
    return {
        "revenue": revenue,
        "transform_cost": transform_cost,
        "hrc_cost": hrc_cost,
        "zinc_cost": zinc_cost,
        "paint_cost": paint_cost,
        "scrap_value": scrap_value,
        "downgraded_value": downgraded_value,
        "nonconforming_value": nonconforming_value,
        "margin_before_timing": margin_before_timing,
        "hrc_input": hrc_input,
        **{f"input_{line}": val for line, val in inputs.items()},
    }


def build_options(data: InputData) -> pd.DataFrame:
    """Create one row for each order-route-production week-delivery week option."""

    rows: list[dict[str, object]] = []
    holding_cost = data.params["Coût stockage produit fini"]
    for order_idx, order in data.orders.iterrows():
        routes = allowed_routes(order)
        for route in routes:
            econ = route_economics(order, route, data)
            for prod_week in WEEKS:
                for delivery_week in WEEKS:
                    if prod_week > delivery_week:
                        continue
                    delay = max(0, delivery_week - int(order["DueWeek"]))
                    delay_penalty = (
                        float(order["Tonnage"])
                        * delay
                        * data.params[f"Pénalité retard commande {order['Priorite']}"]
                    )
                    stock_cost = float(order["Tonnage"]) * max(0, delivery_week - prod_week) * holding_cost
                    margin = econ["margin_before_timing"] - delay_penalty - stock_cost
                    rows.append(
                        {
                            "order_idx": int(order_idx),
                            "order_id": order["ID"],
                            "client": order["Client"],
                            "family": order["Famille"],
                            "grade": order["Grade"],
                            "thickness": float(order["Epaisseur"]),
                            "width": int(order["Largeur"]),
                            "tonnage": float(order["Tonnage"]),
                            "price": float(order["Prix"]),
                            "due_week": int(order["DueWeek"]),
                            "priority": order["Priorite"],
                            "route_id": route.id,
                            "route_lines": ">".join(route.lines),
                            "prod_week": prod_week,
                            "delivery_week": delivery_week,
                            "delay_weeks": delay,
                            "delay_penalty": delay_penalty,
                            "stock_cost": stock_cost,
                            "margin": margin,
                            **econ,
                        }
                    )
    return pd.DataFrame(rows)


def solve_model(
    data: InputData,
    *,
    campaigns: bool = False,
    relax: bool = False,
    hrc_multiplier: float = 1.0,
    extra_lgb_stop_week2: float = 0.0,
    force_accept_order: str | None = None,
    dc01_availability_multiplier: float = 1.0,
    cadence_multiplier: float = 1.0,
    time_limit: int = 300,
    msg: bool = False,
    log_path: str | Path | None = None,
) -> SolveResult:
    """Build and solve the PuLP model."""

    scenario_data = _copy_with_scenario_changes(
        data,
        hrc_multiplier=hrc_multiplier,
        extra_lgb_stop_week2=extra_lgb_stop_week2,
        dc01_availability_multiplier=dc01_availability_multiplier,
        cadence_multiplier=cadence_multiplier,
    )
    options = build_options(scenario_data)
    problem = pulp.LpProblem("MaghrebSteel_Capacite_Commande", pulp.LpMaximize)

    cat = pulp.LpContinuous if relax else pulp.LpBinary
    x: dict[int, pulp.LpVariable] = {
        i: pulp.LpVariable(f"x_{i}", lowBound=0, upBound=1, cat=cat) for i in options.index
    }

    problem += pulp.lpSum(options.loc[i, "margin"] * var for i, var in x.items()), "Marge_totale"

    constraint_meta: dict[str, dict[str, object]] = {}

    for order_idx, group in options.groupby("order_idx"):
        name = f"order_once_{safe_name(str(group.iloc[0]['order_id']))}"
        problem += pulp.lpSum(x[i] for i in group.index) <= 1, name
        constraint_meta[name] = {"type": "order_once", "order_id": group.iloc[0]["order_id"]}

    if force_accept_order is not None:
        forced = options[options["order_id"] == force_accept_order]
        if len(forced) > 0:
            name = f"force_accept_{safe_name(force_accept_order)}"
            problem += pulp.lpSum(x[i] for i in forced.index) == 1, name
            constraint_meta[name] = {"type": "force_accept", "order_id": force_accept_order}

    for grade, availability in scenario_data.hrc_availability.items():
        expr = pulp.lpSum(options.loc[i, "hrc_input"] * x[i] for i in options.index if options.loc[i, "grade"] == grade)
        name = f"hrc_avail_{safe_name(grade)}"
        problem += expr <= availability, name
        constraint_meta[name] = {"type": "hrc", "grade": grade, "rhs": availability}

    flow_expr = _capacity_expressions(options, x)
    z: dict[tuple[str, str, int], pulp.LpVariable] = {}
    for (line, family, week), expr in flow_expr.items():
        cap = capacity_value(scenario_data, line, family, week)
        if cap is None:
            continue
        name = f"cap_{line}_{safe_name(family)}_S{week}"
        if campaigns:
            z[(line, family, week)] = pulp.LpVariable(
                f"z_{line}_{safe_name(family)}_S{week}", lowBound=0, upBound=1, cat=cat
            )
            problem += expr <= cap * z[(line, family, week)], name
            min_name = f"camp_min_{line}_{safe_name(family)}_S{week}"
            problem += expr >= 100.0 * z[(line, family, week)], min_name
            constraint_meta[min_name] = {"type": "campaign_min", "line": line, "family": family, "week": week, "rhs": 100}
        else:
            problem += expr <= cap, name
        constraint_meta[name] = {"type": "capacity", "line": line, "family": family, "week": week, "rhs": cap}

    if campaigns:
        for line in LINES:
            for week in WEEKS:
                keys = [k for k in z if k[0] == line and k[2] == week]
                if keys:
                    name = f"one_campaign_{line}_S{week}"
                    problem += pulp.lpSum(z[k] for k in keys) <= 1, name
                    constraint_meta[name] = {"type": "one_campaign", "line": line, "week": week, "rhs": 1}

    stock_expr = _finished_stock_expressions(options, x, scenario_data)
    for family in MODELED_FAMILIES:
        if family not in scenario_data.finished_stocks:
            continue
        for week in WEEKS:
            stock = stock_expr[(family, week)]
            min_stock = scenario_data.finished_stocks[family]["min"]
            max_stock = scenario_data.finished_stocks[family]["max"]
            min_name = f"stock_min_{safe_name(family)}_S{week}"
            max_name = f"stock_max_{safe_name(family)}_S{week}"
            problem += stock >= min_stock, min_name
            problem += stock <= max_stock, max_name
            constraint_meta[min_name] = {"type": "stock_min", "family": family, "week": week, "rhs": min_stock}
            constraint_meta[max_name] = {"type": "stock_max", "family": family, "week": week, "rhs": max_stock}

    solver = pulp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit, logPath=str(log_path) if log_path else None)
    start = time.perf_counter()
    problem.solve(solver)
    runtime = time.perf_counter() - start

    selected = options.copy()
    selected["value"] = [pulp.value(x[i]) or 0.0 for i in options.index]
    decisions = selected[selected["value"] > 1e-6].copy()
    decisions["delivered_tonnage"] = decisions["tonnage"] * decisions["value"]
    decisions["realized_margin"] = decisions["margin"] * decisions["value"]

    capacity = build_capacity_report(decisions, scenario_data)
    stocks = build_stock_report(decisions, scenario_data)
    hrc = build_hrc_report(decisions, scenario_data)
    orders = build_order_report(data.orders, decisions)
    family_margins = build_family_margins(decisions)
    shadows = build_shadow_report(problem, constraint_meta)
    reduced_costs = build_reduced_cost_report(options, x)
    refused = build_refused_report(orders, options, shadows, reduced_costs)

    metadata = {
        "campaigns": str(campaigns),
        "relax": str(relax),
        "hrc_multiplier": hrc_multiplier,
        "extra_lgb_stop_week2": extra_lgb_stop_week2,
        "dc01_availability_multiplier": dc01_availability_multiplier,
        "cadence_multiplier": cadence_multiplier,
        "variables": len(x) + len(z),
        "constraints": len(problem.constraints),
    }

    return SolveResult(
        status=pulp.LpStatus[problem.status],
        objective=float(pulp.value(problem.objective) or 0.0),
        runtime_s=runtime,
        decisions=decisions,
        orders=orders,
        capacity=capacity,
        stocks=stocks,
        hrc=hrc,
        shadows=shadows,
        reduced_costs=reduced_costs,
        family_margins=family_margins,
        refused=refused,
        metadata=metadata,
    )


def _copy_with_scenario_changes(
    data: InputData,
    *,
    hrc_multiplier: float,
    extra_lgb_stop_week2: float,
    dc01_availability_multiplier: float,
    cadence_multiplier: float,
) -> InputData:
    prices = {k: v * hrc_multiplier for k, v in data.hrc_prices.items()}
    stops = dict(data.stops)
    stops[("LGB", 2)] = stops.get(("LGB", 2), 0.0) + extra_lgb_stop_week2
    availability = dict(data.hrc_availability)
    availability["DC01"] = availability["DC01"] * dc01_availability_multiplier
    cadences = {k: v * cadence_multiplier for k, v in data.cadences.items()}
    return InputData(
        orders=data.orders,
        cadences=cadences,
        yields=data.yields,
        scrap_rates=data.scrap_rates,
        downgraded_rates=data.downgraded_rates,
        nonconforming_rates=data.nonconforming_rates,
        costs=data.costs,
        hrc_prices=prices,
        hrc_availability=availability,
        finished_stocks=data.finished_stocks,
        interprocess_stocks=data.interprocess_stocks,
        pk_stocks=data.pk_stocks,
        stops=stops,
        params=data.params,
    )


def capacity_value(data: InputData, line: str, family: str, week: int) -> float | None:
    cadence = data.cadences.get((line, family))
    if cadence is None:
        return None
    return max(0.0, cadence * (data.params["Jours ouvrés / semaine"] - data.stops.get((line, week), 0.0)))


def _capacity_expressions(options: pd.DataFrame, x: dict[int, pulp.LpVariable]) -> dict[tuple[str, str, int], pulp.LpAffineExpression]:
    exprs: dict[tuple[str, str, int], pulp.LpAffineExpression] = {}
    for i, row in options.iterrows():
        for line in str(row["route_lines"]).split(">"):
            key = (line, str(row["family"]), int(row["prod_week"]))
            exprs.setdefault(key, pulp.LpAffineExpression())
            exprs[key] += float(row.get(f"input_{line}", 0.0)) * x[i]
    return exprs


def _finished_stock_expressions(
    options: pd.DataFrame, x: dict[int, pulp.LpVariable], data: InputData
) -> dict[tuple[str, int], pulp.LpAffineExpression]:
    exprs: dict[tuple[str, int], pulp.LpAffineExpression] = {}
    for family in MODELED_FAMILIES:
        initial = data.finished_stocks.get(family, {}).get("initial", 0.0)
        for week in WEEKS:
            expr = pulp.LpAffineExpression(initial)
            for i, row in options[options["family"] == family].iterrows():
                if int(row["prod_week"]) <= week:
                    expr += float(row["tonnage"]) * x[i]
                if int(row["delivery_week"]) <= week:
                    expr -= float(row["tonnage"]) * x[i]
            exprs[(family, week)] = expr
    return exprs


def build_capacity_report(decisions: pd.DataFrame, data: InputData) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for line in LINES:
        for family in MODELED_FAMILIES:
            for week in WEEKS:
                cap = capacity_value(data, line, family, week)
                if cap is None:
                    continue
                used = 0.0
                if not decisions.empty:
                    subset = decisions[(decisions["family"] == family) & (decisions["prod_week"] == week)]
                    for _, row in subset.iterrows():
                        if line in str(row["route_lines"]).split(">"):
                            used += float(row.get(f"input_{line}", 0.0)) * float(row["value"])
                rows.append(
                    {
                        "line": line,
                        "family": family,
                        "week": week,
                        "used_t": used,
                        "capacity_t": cap,
                        "utilization": used / cap if cap else 0.0,
                        "slack_t": cap - used,
                    }
                )
    return pd.DataFrame(rows)


def build_stock_report(decisions: pd.DataFrame, data: InputData) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for family, limits in data.finished_stocks.items():
        stock = limits["initial"]
        for week in WEEKS:
            produced = decisions[(decisions["family"] == family) & (decisions["prod_week"] == week)]["delivered_tonnage"].sum()
            delivered = decisions[(decisions["family"] == family) & (decisions["delivery_week"] == week)]["delivered_tonnage"].sum()
            stock += produced - delivered
            rows.append(
                {
                    "stock_type": "finished",
                    "family_or_point": family,
                    "week": week,
                    "stock_t": stock,
                    "min_t": limits["min"],
                    "max_t": limits["max"],
                    "within_bounds": limits["min"] - 1e-5 <= stock <= limits["max"] + 1e-5,
                }
            )
    for point, limits in data.interprocess_stocks.items():
        for week in WEEKS:
            rows.append(
                {
                    "stock_type": "interprocess_buffer",
                    "family_or_point": point,
                    "week": week,
                    "stock_t": limits["initial"],
                    "min_t": limits["min"],
                    "max_t": limits["max"],
                    "within_bounds": limits["min"] <= limits["initial"] <= limits["max"],
                }
            )
    return pd.DataFrame(rows)


def build_hrc_report(decisions: pd.DataFrame, data: InputData) -> pd.DataFrame:
    rows = []
    for grade, avail in data.hrc_availability.items():
        used = decisions[decisions["grade"] == grade]["hrc_input"].mul(decisions[decisions["grade"] == grade]["value"]).sum()
        rows.append({"grade": grade, "used_t": used, "available_t": avail, "slack_t": avail - used, "utilization": used / avail})
    return pd.DataFrame(rows)


def build_order_report(all_orders: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    by_order = decisions.groupby("order_id") if not decisions.empty else {}
    for _, order in all_orders.iterrows():
        order_id = order["ID"]
        if isinstance(by_order, dict) or order_id not in by_order.groups:
            rows.append(
                {
                    "order_id": order_id,
                    "client": order["Client"],
                    "family": order["Famille"],
                    "grade": order["Grade"],
                    "thickness": order["Epaisseur"],
                    "width": order["Largeur"],
                    "tonnage": order["Tonnage"],
                    "price": order["Prix"],
                    "due_week": order["DueWeek"],
                    "priority": order["Priorite"],
                    "accepted": False,
                    "route_id": "",
                    "route_lines": "",
                    "prod_week": "",
                    "delivery_week": "",
                    "delay_weeks": "",
                    "realized_margin": 0.0,
                }
            )
        else:
            rowsel = by_order.get_group(order_id).sort_values("value", ascending=False).iloc[0]
            rows.append(
                {
                    "order_id": order_id,
                    "client": order["Client"],
                    "family": order["Famille"],
                    "grade": order["Grade"],
                    "thickness": order["Epaisseur"],
                    "width": order["Largeur"],
                    "tonnage": order["Tonnage"],
                    "price": order["Prix"],
                    "due_week": order["DueWeek"],
                    "priority": order["Priorite"],
                    "accepted": bool(rowsel["value"] > 0.5),
                    "route_id": rowsel["route_id"],
                    "route_lines": rowsel["route_lines"],
                    "prod_week": int(rowsel["prod_week"]),
                    "delivery_week": int(rowsel["delivery_week"]),
                    "delay_weeks": int(rowsel["delay_weeks"]),
                    "realized_margin": float(rowsel["realized_margin"]),
                }
            )
    return pd.DataFrame(rows)


def build_family_margins(decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty:
        return pd.DataFrame(columns=["family", "delivered_tonnage", "margin", "margin_per_t"])
    grp = decisions.groupby("family").agg(delivered_tonnage=("delivered_tonnage", "sum"), margin=("realized_margin", "sum"))
    grp["margin_per_t"] = grp["margin"] / grp["delivered_tonnage"]
    return grp.reset_index().sort_values("margin_per_t", ascending=False)


def build_shadow_report(problem: pulp.LpProblem, meta: dict[str, dict[str, object]]) -> pd.DataFrame:
    rows = []
    for name, con in problem.constraints.items():
        info = meta.get(name, {})
        rows.append(
            {
                "constraint": name,
                "type": info.get("type", ""),
                "line": info.get("line", ""),
                "family": info.get("family", ""),
                "week": info.get("week", ""),
                "grade": info.get("grade", ""),
                "rhs": info.get("rhs", ""),
                "slack": con.slack,
                "shadow_price": con.pi,
            }
        )
    return pd.DataFrame(rows).sort_values("shadow_price", key=lambda s: s.abs(), ascending=False)


def build_reduced_cost_report(options: pd.DataFrame, x: dict[int, pulp.LpVariable]) -> pd.DataFrame:
    rows = []
    for i, row in options.iterrows():
        rows.append(
            {
                "option_idx": i,
                "order_id": row["order_id"],
                "route_id": row["route_id"],
                "prod_week": row["prod_week"],
                "delivery_week": row["delivery_week"],
                "margin": row["margin"],
                "value": pulp.value(x[i]) or 0.0,
                "reduced_cost": x[i].dj,
            }
        )
    return pd.DataFrame(rows)


def build_refused_report(
    orders: pd.DataFrame, options: pd.DataFrame, shadows: pd.DataFrame, reduced_costs: pd.DataFrame
) -> pd.DataFrame:
    refused = orders[~orders["accepted"]].copy()
    if refused.empty:
        return refused

    scarce = shadows[
        (shadows["type"].isin(["capacity", "hrc", "stock_min", "stock_max"]))
        & (shadows["shadow_price"].abs() > 1e-5)
    ].copy()

    reasons = []
    for _, order in refused.iterrows():
        oid = order["order_id"]
        opts = options[options["order_id"] == oid]
        if opts.empty:
            reasons.append("Routage impossible ou hors périmètre")
            continue
        rc = reduced_costs[reduced_costs["order_id"] == oid]["reduced_cost"].max()
        candidate_reasons: list[str] = []
        grade_rows = scarce[(scarce["type"] == "hrc") & (scarce["grade"] == order["grade"])]
        if not grade_rows.empty:
            candidate_reasons.append(f"HRC grade {order['grade']} rare")
        for _, opt in opts.head(20).iterrows():
            route_lines = str(opt["route_lines"]).split(">")
            for line in route_lines:
                cap_rows = scarce[
                    (scarce["type"] == "capacity")
                    & (scarce["line"] == line)
                    & (scarce["family"] == order["family"])
                ]
                if not cap_rows.empty:
                    row = cap_rows.iloc[0]
                    candidate_reasons.append(f"Capacité {line}/{order['family']} semaine {row['week']}")
        if candidate_reasons:
            reason = candidate_reasons[0]
        elif pd.notna(rc) and rc < 0:
            reason = "Coût réduit négatif dans la relaxation LP"
        else:
            reason = "Marge/opportunité inférieure aux commandes retenues"
        reasons.append(reason)
    refused["blocking_reason"] = reasons
    return refused


def export_result(result: SolveResult, out_dir: str | Path, prefix: str = "base") -> None:
    """Write all result tables to CSV and a multi-sheet Excel workbook."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "decisions": result.decisions,
        "orders": result.orders,
        "capacity": result.capacity,
        "stocks": result.stocks,
        "hrc": result.hrc,
        "shadows": result.shadows,
        "reduced_costs": result.reduced_costs,
        "family_margins": result.family_margins,
        "refused": result.refused,
    }
    for name, df in tables.items():
        df.to_csv(out / f"{prefix}_{name}.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out / f"{prefix}_resultats.xlsx", engine="xlsxwriter") as writer:
        for name, df in tables.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)


def parse_cbc_nodes(log_path: str | Path) -> int | None:
    path = Path(log_path)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"Enumerated nodes:\s+(\d+)", text)
    return int(match.group(1)) if match else None
