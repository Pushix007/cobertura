from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import math
import re
import unicodedata

import numpy as np
import pandas as pd


@dataclass
class AnalysisConfig:
    window_days: int = 90
    min_days: int = 30
    target_days: int = 45
    max_days: int = 75
    reserve_units: int = 1
    prioritize_same_regional: bool = True
    allow_flexible_color: bool = True


def _clean_text(value) -> str:
    if pd.isna(value):
        return "NAO INFORMADO"
    text = str(value).strip().upper()
    text = re.sub(r"\s+", " ", text)
    return text if text else "NAO INFORMADO"


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def normalize_column_name(name: str) -> str:
    text = _strip_accents(str(name).strip().lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def auto_pick(columns: Iterable[str], aliases: list[str]) -> str | None:
    normalized = {col: normalize_column_name(col) for col in columns}
    alias_norm = [normalize_column_name(a) for a in aliases]

    for alias in alias_norm:
        for col, ncol in normalized.items():
            if ncol == alias:
                return col
    for alias in alias_norm:
        for col, ncol in normalized.items():
            if alias in ncol or ncol in alias:
                return col
    return None


def prepare_stock(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for field in ["regional", "loja", "familia", "modelo", "versao", "cor"]:
        col = mapping.get(field)
        if col and col in df.columns:
            out[field] = df[col].map(_clean_text)
        else:
            out[field] = "NAO INFORMADO"

    qty_col = mapping.get("quantidade")
    if qty_col and qty_col in df.columns:
        out["estoque"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    else:
        out["estoque"] = 1.0

    age_col = mapping.get("data_entrada")
    if age_col and age_col in df.columns:
        out["data_entrada"] = pd.to_datetime(df[age_col], errors="coerce", dayfirst=True)
    else:
        out["data_entrada"] = pd.NaT

    return out


def prepare_sales(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for field in ["regional", "loja", "familia", "modelo", "versao", "cor"]:
        col = mapping.get(field)
        if col and col in df.columns:
            out[field] = df[col].map(_clean_text)
        else:
            out[field] = "NAO INFORMADO"

    qty_col = mapping.get("quantidade")
    if qty_col and qty_col in df.columns:
        out["vendas"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    else:
        out["vendas"] = 1.0

    date_col = mapping.get("data")
    if not date_col or date_col not in df.columns:
        raise ValueError("A base de vendas precisa de uma coluna de data.")
    out["data"] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    out = out[out["data"].notna()].copy()
    return out


def infer_regional_from_stock(stock: pd.DataFrame, sales: pd.DataFrame) -> pd.DataFrame:
    if sales["regional"].eq("NAO INFORMADO").all():
        lookup = (
            stock.loc[stock["regional"].ne("NAO INFORMADO"), ["loja", "regional"]]
            .drop_duplicates()
            .drop_duplicates(subset=["loja"], keep="first")
        )
        sales = sales.drop(columns=["regional"]).merge(lookup, on="loja", how="left")
        sales["regional"] = sales["regional"].fillna("NAO INFORMADO")
    return sales


def filter_sales_window(sales: pd.DataFrame, window_days: int) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    if sales.empty:
        raise ValueError("A base de vendas não possui datas válidas.")
    reference_date = pd.Timestamp(sales["data"].max()).normalize()
    start_date = reference_date - pd.Timedelta(days=window_days - 1)
    filtered = sales[(sales["data"] >= start_date) & (sales["data"] <= reference_date + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1))].copy()
    return filtered, start_date, reference_date


def _aggregate_stock(stock: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    agg = stock.groupby(group_cols, dropna=False, as_index=False).agg(
        estoque=("estoque", "sum"),
        data_entrada_media=("data_entrada", "mean"),
        data_entrada_mais_antiga=("data_entrada", "min"),
    )
    return agg


def _aggregate_sales(sales: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return sales.groupby(group_cols, dropna=False, as_index=False).agg(vendas_periodo=("vendas", "sum"))


def build_analysis(stock: pd.DataFrame, sales: pd.DataFrame, group_cols: list[str], cfg: AnalysisConfig) -> pd.DataFrame:
    sales_window, _, reference_date = filter_sales_window(sales, cfg.window_days)
    s = _aggregate_stock(stock, group_cols)
    v = _aggregate_sales(sales_window, group_cols)
    df = s.merge(v, on=group_cols, how="outer")

    df["estoque"] = df["estoque"].fillna(0).astype(float)
    df["vendas_periodo"] = df["vendas_periodo"].fillna(0).astype(float)
    df["media_venda_dia"] = df["vendas_periodo"] / float(cfg.window_days)
    df["media_venda_mes"] = df["media_venda_dia"] * 30.0

    positive_sales = df["media_venda_dia"] > 0
    df["cobertura_dias"] = np.where(
        positive_sales,
        df["estoque"] / df["media_venda_dia"],
        np.where(df["estoque"] > 0, np.inf, 0.0),
    )
    df["estoque_ideal"] = np.ceil(df["media_venda_dia"] * cfg.target_days)
    df["estoque_minimo"] = np.ceil(df["media_venda_dia"] * cfg.min_days)
    df["estoque_maximo"] = np.ceil(df["media_venda_dia"] * cfg.max_days)

    df["falta_qtd"] = 0.0
    mask_falta = positive_sales & (df["cobertura_dias"] < cfg.min_days)
    df.loc[mask_falta, "falta_qtd"] = (
        df.loc[mask_falta, "estoque_ideal"] - df.loc[mask_falta, "estoque"]
    ).clip(lower=0)

    df["excesso_qtd"] = 0.0
    mask_excesso = positive_sales & (df["cobertura_dias"] > cfg.max_days)
    df.loc[mask_excesso, "excesso_qtd"] = (
        df.loc[mask_excesso, "estoque"] - df.loc[mask_excesso, "estoque_ideal"]
    ).clip(lower=0)
    mask_sem_giro = (~positive_sales) & (df["estoque"] > 0)
    df.loc[mask_sem_giro, "excesso_qtd"] = df.loc[mask_sem_giro, "estoque"]

    conditions = [
        (df["estoque"] <= 0) & positive_sales,
        mask_sem_giro,
        mask_falta,
        mask_excesso,
        (df["estoque"] > 0) | positive_sales,
    ]
    choices = ["RUPTURA", "SEM GIRO", "FALTA", "EXCESSO", "ADEQUADO"]
    df["status"] = np.select(conditions, choices, default="SEM MOVIMENTO")

    if "data_entrada_mais_antiga" in df.columns:
        df["idade_estoque_dias"] = (
            reference_date - pd.to_datetime(df["data_entrada_mais_antiga"], errors="coerce")
        ).dt.days

    numeric_cols = ["estoque", "vendas_periodo", "estoque_ideal", "estoque_minimo", "estoque_maximo", "falta_qtd", "excesso_qtd"]
    for col in numeric_cols:
        df[col] = df[col].round(0).astype(int)
    df["media_venda_mes"] = df["media_venda_mes"].round(2)
    df["media_venda_dia"] = df["media_venda_dia"].round(4)
    return df


def coverage_display(value) -> str:
    if pd.isna(value):
        return "-"
    if np.isinf(value):
        return "Sem giro"
    return f"{value:.0f} d"


def _availability_for_transfer(row: pd.Series, cfg: AnalysisConfig) -> int:
    stock = int(row["estoque"])
    ideal = int(row["estoque_ideal"])
    reserve = max(cfg.reserve_units, ideal)
    if row["status"] == "SEM GIRO":
        reserve = cfg.reserve_units
    return max(stock - reserve, 0)


def _need_for_transfer(row: pd.Series) -> int:
    if row["status"] not in {"RUPTURA", "FALTA"}:
        return 0
    return max(int(row["estoque_ideal"]) - int(row["estoque"]), 0)


def _coverage(stock: float, daily: float) -> float:
    if daily <= 0:
        return math.inf if stock > 0 else 0.0
    return stock / daily


def suggest_transfers(detail: pd.DataFrame, cfg: AnalysisConfig, use_version: bool = True, exact_color: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = detail.copy()
    base["disponivel_transferencia"] = base.apply(lambda r: _availability_for_transfer(r, cfg), axis=1)
    base["necessidade_transferencia"] = base.apply(_need_for_transfer, axis=1)

    match_cols = ["familia", "modelo"]
    if use_version and "versao" in base.columns:
        match_cols.append("versao")
    if exact_color and "cor" in base.columns:
        match_cols.append("cor")

    transfers: list[dict] = []
    remaining_stock = base["estoque"].astype(float).to_dict()
    remaining_avail = base["disponivel_transferencia"].astype(int).to_dict()
    remaining_need = base["necessidade_transferencia"].astype(int).to_dict()

    recipients = base[base["necessidade_transferencia"] > 0].copy()
    recipients["coverage_sort"] = recipients["cobertura_dias"].replace(np.inf, 10**9)
    recipients = recipients.sort_values(["coverage_sort", "media_venda_dia"], ascending=[True, False])

    for ridx, rec in recipients.iterrows():
        need = remaining_need.get(ridx, 0)
        if need <= 0:
            continue
        mask = pd.Series(True, index=base.index)
        for col in match_cols:
            mask &= base[col].eq(rec[col])
        mask &= base["disponivel_transferencia"].gt(0)
        mask &= base["loja"].ne(rec["loja"])
        donors = base.loc[mask].copy()
        if donors.empty:
            continue

        donors["same_regional"] = donors["regional"].eq(rec["regional"])
        donors["coverage_sort"] = donors["cobertura_dias"].replace(np.inf, 10**9)
        sort_cols = []
        ascending = []
        if cfg.prioritize_same_regional:
            sort_cols.append("same_regional")
            ascending.append(False)
        sort_cols += ["coverage_sort", "idade_estoque_dias" if "idade_estoque_dias" in donors.columns else "estoque"]
        ascending += [False, False]
        donors = donors.sort_values(sort_cols, ascending=ascending)

        for didx, donor in donors.iterrows():
            avail = remaining_avail.get(didx, 0)
            if avail <= 0 or need <= 0:
                continue
            qty = min(avail, need)
            donor_before = remaining_stock[didx]
            rec_before = remaining_stock[ridx]
            donor_after = donor_before - qty
            rec_after = rec_before + qty

            transfers.append({
                "origem_regional": donor["regional"],
                "origem_loja": donor["loja"],
                "destino_regional": rec["regional"],
                "destino_loja": rec["loja"],
                "familia": rec.get("familia", ""),
                "modelo": rec.get("modelo", ""),
                "versao": rec.get("versao", ""),
                "cor_origem": donor.get("cor", ""),
                "cor_destino_referencia": rec.get("cor", ""),
                "quantidade": int(qty),
                "tipo_pareamento": "EXATO" if exact_color else "COR FLEXIVEL",
                "cobertura_origem_antes": _coverage(donor_before, float(donor["media_venda_dia"])),
                "cobertura_origem_depois": _coverage(donor_after, float(donor["media_venda_dia"])),
                "cobertura_destino_antes": _coverage(rec_before, float(rec["media_venda_dia"])),
                "cobertura_destino_depois": _coverage(rec_after, float(rec["media_venda_dia"])),
                "venda_media_mes_destino": float(rec["media_venda_mes"]),
            })
            remaining_stock[didx] = donor_after
            remaining_stock[ridx] = rec_after
            remaining_avail[didx] -= qty
            remaining_need[ridx] -= qty
            need -= qty
            if need <= 0:
                break

    transfer_df = pd.DataFrame(transfers)
    residual = base.copy()
    residual["necessidade_residual"] = [remaining_need.get(i, 0) for i in residual.index]
    residual = residual[residual["necessidade_residual"] > 0].copy()
    return transfer_df, residual


def build_transfer_plan(detail: pd.DataFrame, cfg: AnalysisConfig, use_version: bool = True) -> pd.DataFrame:
    exact, residual = suggest_transfers(detail, cfg, use_version=use_version, exact_color=True)
    if not cfg.allow_flexible_color or residual.empty:
        return exact

    flexible, _ = suggest_transfers(detail, cfg, use_version=use_version, exact_color=False)
    if flexible.empty:
        return exact

    # Necessidade ainda não atendida depois das sugestões exatas.
    residual_need = {
        (r["regional"], r["loja"], r["familia"], r["modelo"], r.get("versao", ""), r["cor"]): int(r["necessidade_residual"])
        for _, r in residual.iterrows()
    }

    # Disponibilidade original de cada doador, descontando o que já foi usado na etapa exata.
    donor_available = {}
    for _, r in detail.iterrows():
        key = (r["regional"], r["loja"], r["familia"], r["modelo"], r.get("versao", ""), r["cor"])
        donor_available[key] = _availability_for_transfer(r, cfg)
    if not exact.empty:
        for _, r in exact.iterrows():
            key = (r["origem_regional"], r["origem_loja"], r["familia"], r["modelo"], r.get("versao", ""), r["cor_origem"])
            donor_available[key] = max(donor_available.get(key, 0) - int(r["quantidade"]), 0)

    kept = []
    for _, row in flexible.iterrows():
        recipient_key = (
            row["destino_regional"], row["destino_loja"], row["familia"], row["modelo"], row.get("versao", ""), row["cor_destino_referencia"]
        )
        donor_key = (
            row["origem_regional"], row["origem_loja"], row["familia"], row["modelo"], row.get("versao", ""), row["cor_origem"]
        )
        need = residual_need.get(recipient_key, 0)
        avail = donor_available.get(donor_key, 0)
        if need <= 0 or avail <= 0:
            continue
        qty = min(int(row["quantidade"]), need, avail)
        if qty <= 0:
            continue
        row = row.copy()
        row["quantidade"] = qty
        row["tipo_pareamento"] = "COR FLEXIVEL"
        kept.append(row.to_dict())
        residual_need[recipient_key] -= qty
        donor_available[donor_key] -= qty

    flex_df = pd.DataFrame(kept)
    if exact.empty:
        return flex_df
    if flex_df.empty:
        return exact
    return pd.concat([exact, flex_df], ignore_index=True)
