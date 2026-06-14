"""Chargement et normalisation des donnees Maghreb Steel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


WEEKS = [1, 2, 3, 4]


@dataclass(frozen=True)
class InputData:
    orders: pd.DataFrame
    cadences: dict[tuple[str, str], float]
    yields: dict[str, float]
    scrap_rates: dict[str, float]
    downgraded_rates: dict[str, float]
    nonconforming_rates: dict[str, float]
    costs: dict[str, dict[str, float]]
    hrc_prices: dict[tuple[str, int], float]
    hrc_availability: dict[str, float]
    finished_stocks: dict[str, dict[str, float]]
    interprocess_stocks: dict[str, dict[str, float]]
    pk_stocks: dict[str, dict[str, float]]
    stops: dict[tuple[str, int], float]
    params: dict[str, float]


def _clean_dash(value: Any) -> float | None:
    if pd.isna(value) or str(value).strip() in {"-", "—", ""}:
        return None
    return float(value)


def _read_table(path: Path, sheet: str, header_row: int) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet, header=header_row)


def load_data(path: str | Path) -> InputData:
    """Read the project workbook and return typed dictionaries used by the model."""

    path = Path(path)

    orders = _read_table(path, "Commandes", 2).dropna(subset=["ID"]).copy()
    orders = orders.rename(
        columns={
            "Épaisseur (mm)": "Epaisseur",
            "Largeur (mm)": "Largeur",
            "Tonnage (T)": "Tonnage",
            "Prix vente (MAD/T)": "Prix",
            "Semaine livraison": "DueWeek",
            "Priorité": "Priorite",
        }
    )
    orders["Largeur"] = orders["Largeur"].astype(int)
    orders["DueWeek"] = orders["DueWeek"].astype(int)
    orders["Tonnage"] = orders["Tonnage"].astype(float)
    orders["Prix"] = orders["Prix"].astype(float)
    orders["Epaisseur"] = orders["Epaisseur"].astype(float)

    cad = _read_table(path, "Cadences", 2)
    cadences: dict[tuple[str, str], float] = {}
    for _, row in cad.iterrows():
        line = row.iloc[0]
        if pd.isna(line) or str(line).startswith("Règles"):
            break
        for fam in cad.columns[1:]:
            value = _clean_dash(row[fam])
            if value is not None:
                cadences[(str(line), str(fam))] = value

    rend = _read_table(path, "Rendements", 2)
    rend = rend.dropna(subset=["Process"]).iloc[:7]
    yields = {str(r["Process"]): float(r["Rendement (%)"]) for _, r in rend.iterrows()}
    scrap = {str(r["Process"]): float(r["Chute (%)"]) for _, r in rend.iterrows()}
    downgraded = {str(r["Process"]): float(r["Déclassé (%)"]) for _, r in rend.iterrows()}
    nonconf = {str(r["Process"]): float(r["Non-conforme (%)"]) for _, r in rend.iterrows()}

    cst = _read_table(path, "Couts_Variables", 2)
    cst = cst.dropna(subset=["Process \\ Épaisseur (mm)"])
    cst = cst[~cst["Process \\ Épaisseur (mm)"].astype(str).str.startswith("Coûts")]
    costs: dict[str, dict[str, float]] = {}
    for _, row in cst.iterrows():
        process = str(row["Process \\ Épaisseur (mm)"])
        costs[process] = {str(col): float(row[col]) for col in cst.columns[1:] if not pd.isna(row[col])}

    prix = pd.read_excel(path, sheet_name="Prix_HRC", header=None)
    header = prix.iloc[2].tolist()
    hrc_prices: dict[tuple[str, int], float] = {}
    for i in range(3, 8):
        grade = str(prix.iloc[i, 0])
        for j, width in enumerate(header[1:8], start=1):
            hrc_prices[(grade, int(width))] = float(prix.iloc[i, j])
    hrc_availability = {
        str(prix.iloc[i, 0]): float(prix.iloc[i, 1])
        for i in range(12, 17)
        if not pd.isna(prix.iloc[i, 0])
    }

    stocks_raw = pd.read_excel(path, sheet_name="Stocks_Initiaux", header=None)
    pk_stocks = _extract_stock_block(stocks_raw, "Grade", 4, ["initial", "min", "max"])
    interprocess_stocks = _extract_stock_block(stocks_raw, "Point de stockage", 13, ["initial", "min", "max"])
    finished_stocks = _extract_stock_block(stocks_raw, "Famille", 21, ["initial", "min", "max"])

    stops_df = _read_table(path, "Arrets_Planifies", 2)
    stops: dict[tuple[str, int], float] = {}
    for _, row in stops_df.iterrows():
        line = row.iloc[0]
        if pd.isna(line) or str(line).startswith("Calcul"):
            break
        for week in WEEKS:
            stops[(str(line), week)] = float(row[f"Semaine {week}"])

    params_df = _read_table(path, "Parametres", 2).dropna(subset=["Paramètre"])
    params = {str(row["Paramètre"]): float(row["Valeur"]) for _, row in params_df.iterrows()}

    return InputData(
        orders=orders,
        cadences=cadences,
        yields=yields,
        scrap_rates=scrap,
        downgraded_rates=downgraded,
        nonconforming_rates=nonconf,
        costs=costs,
        hrc_prices=hrc_prices,
        hrc_availability=hrc_availability,
        finished_stocks=finished_stocks,
        interprocess_stocks=interprocess_stocks,
        pk_stocks=pk_stocks,
        stops=stops,
        params=params,
    )


def _extract_stock_block(raw: pd.DataFrame, first_header: str, header_row: int, names: list[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    row = header_row
    while row < len(raw):
        key = raw.iloc[row, 0]
        if pd.isna(key) or str(key) in {"Stocks interprocess (Full Hard, après CRM)", "Stocks produits finis (par famille)"}:
            break
        if str(key) == first_header:
            row += 1
            continue
        vals = raw.iloc[row, 1 : 1 + len(names)].tolist()
        if all(pd.isna(v) for v in vals):
            break
        out[str(key)] = {name: float(value) for name, value in zip(names, vals)}
        row += 1
    return out


def thickness_bucket(thickness: float) -> str:
    """Return the cost-table interval containing the order thickness."""

    if thickness < 0.3:
        return "<0.3"
    if thickness < 0.4:
        return "0.3-0.4"
    if thickness < 0.5:
        return "0.4-0.5"
    if thickness < 0.7:
        return "0.5-0.7"
    if thickness < 1.0:
        return "0.7-1.0"
    if thickness < 1.5:
        return "1.0-1.5"
    return ">1.5"
