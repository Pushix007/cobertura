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
    # None = usar todo o período existente na base de vendas.
    window_days: int | None = None
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


def normalize_family(value) -> str:
    """Normaliza a família Toyota sem alterar famílias Lexus.

    Nas bases reais recebidas, a mesma família aparece como, por exemplo,
    'TOY HILUX' e 'HILUX'. O prefixo TOY é removido para evitar quebra da
    cobertura e das sugestões de transferência.
    """
    text = _clean_text(value)
    if text.startswith("TOY "):
        text = text[4:].strip()
    return text


def derive_brand(family: str, model: str = "") -> str:
    family = _clean_text(family)
    model = _clean_text(model)
    if family.startswith("LEX") or "LEXUS" in family or "LEXUS" in model:
        return "LEXUS"
    return "TOYOTA"


def _parse_excel_or_date(series: pd.Series) -> pd.Series:
    """Aceita datas já convertidas pelo Excel ou seriais numéricos."""
    numeric = pd.to_numeric(series, errors="coerce")
    dt = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    numeric_mask = numeric.notna()
    if numeric_mask.any():
        dt.loc[numeric_mask] = pd.Timestamp("1899-12-30") + pd.to_timedelta(
            numeric.loc[numeric_mask], unit="D"
        )
    text_mask = ~numeric_mask
    if text_mask.any():
        dt.loc[text_mask] = pd.to_datetime(
            series.loc[text_mask], errors="coerce", format="mixed", dayfirst=True
        )
    return dt


def prepare_stock(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    text_fields = ["regional", "loja", "familia", "modelo", "cor", "patio", "chassi"]
    for field in text_fields:
        col = mapping.get(field)
        if col and col in df.columns:
            out[field] = df[col].map(_clean_text)
        else:
            out[field] = "NAO INFORMADO"

    out["familia_original"] = out["familia"]
    out["familia"] = out["familia"].map(normalize_family)
    out["marca"] = [derive_brand(f, m) for f, m in zip(out["familia"], out["modelo"])]

    qty_col = mapping.get("quantidade")
    if qty_col and qty_col in df.columns:
        out["estoque"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    else:
        out["estoque"] = 1.0

    age_col = mapping.get("data_entrada")
    if age_col and age_col in df.columns:
        out["data_entrada"] = _parse_excel_or_date(df[age_col])
    else:
        out["data_entrada"] = pd.NaT

    # Quando cada linha representa um chassi, evita duplicidade acidental.
    if not (out["chassi"] == "NAO INFORMADO").all() and not qty_col:
        out = out.drop_duplicates(subset=["chassi"], keep="first").copy()
    return out


def prepare_sales(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    text_fields = ["regional", "loja", "familia", "modelo", "cor", "chassi"]
    for field in text_fields:
        col = mapping.get(field)
        if col and col in df.columns:
            out[field] = df[col].map(_clean_text)
        else:
            out[field] = "NAO INFORMADO"

    out["familia_original"] = out["familia"]
    out["familia"] = out["familia"].map(normalize_family)
    out["marca"] = [derive_brand(f, m) for f, m in zip(out["familia"], out["modelo"])]

    qty_col = mapping.get("quantidade")
    if qty_col and qty_col in df.columns:
        out["vendas"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    else:
        out["vendas"] = 1.0

    date_col = mapping.get("data")
    if not date_col or date_col not in df.columns:
        raise ValueError("A base de vendas precisa de uma coluna de data.")
    out["data"] = _parse_excel_or_date(df[date_col])
    out = out[out["data"].notna()].copy()

    if not (out["chassi"] == "NAO INFORMADO").all() and not qty_col:
        # Se houver repetição do mesmo chassi, preserva a venda mais recente.
        out = out.sort_values("data").drop_duplicates(subset=["chassi"], keep="last").copy()
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


def sales_period(sales: pd.DataFrame, window_days: int | None) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    if sales.empty:
        raise ValueError("A base de vendas não possui datas válidas.")
    reference_date = pd.Timestamp(sales["data"].max()).normalize()
    data_start = pd.Timestamp(sales["data"].min()).normalize()
    if window_days is None:
        start_date = data_start
    else:
        start_date = max(data_start, reference_date - pd.Timedelta(days=int(window_days) - 1))
    effective_days = int((reference_date - start_date).days) + 1
    return start_date, reference_date, max(effective_days, 1)


def filter_sales_window(sales: pd.DataFrame, window_days: int | None) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, int]:
    start_date, reference_date, effective_days = sales_period(sales, window_days)
    end_exclusive = reference_date + pd.Timedelta(days=1)
    filtered = sales[(sales["data"] >= start_date) & (sales["data"] < end_exclusive)].copy()
    return filtered, start_date, reference_date, effective_days


def _aggregate_stock(stock: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return stock.groupby(group_cols, dropna=False, as_index=False).agg(
        estoque=("estoque", "sum"),
        data_entrada_media=("data_entrada", "mean"),
        data_entrada_mais_antiga=("data_entrada", "min"),
    )


def _aggregate_sales(sales: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    return sales.groupby(group_cols, dropna=False, as_index=False).agg(vendas_periodo=("vendas", "sum"))


def build_analysis(stock: pd.DataFrame, sales: pd.DataFrame, group_cols: list[str], cfg: AnalysisConfig) -> pd.DataFrame:
    sales_window, start_date, reference_date, effective_days = filter_sales_window(sales, cfg.window_days)
    s = _aggregate_stock(stock, group_cols)
    v = _aggregate_sales(sales_window, group_cols)
    df = s.merge(v, on=group_cols, how="outer")

    df["estoque"] = df["estoque"].fillna(0).astype(float)
    df["vendas_periodo"] = df["vendas_periodo"].fillna(0).astype(float)
    df["periodo_dias"] = effective_days
    df["media_venda_dia"] = df["vendas_periodo"] / float(effective_days)
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
    mask_cobertura_alta = positive_sales & (df["cobertura_dias"] > cfg.max_days)
    df.loc[mask_cobertura_alta, "excesso_qtd"] = (
        df.loc[mask_cobertura_alta, "estoque"] - df.loc[mask_cobertura_alta, "estoque_ideal"]
    ).clip(lower=0)
    mask_excesso = mask_cobertura_alta & (df["excesso_qtd"] > 0)
    mask_elevado = mask_cobertura_alta & (df["excesso_qtd"] <= 0)
    mask_sem_giro = (~positive_sales) & (df["estoque"] > 0)
    df.loc[mask_sem_giro, "excesso_qtd"] = (df.loc[mask_sem_giro, "estoque"] - cfg.reserve_units).clip(lower=0)

    conditions = [
        (df["estoque"] <= 0) & positive_sales,
        mask_sem_giro,
        mask_falta,
        mask_excesso,
        mask_elevado,
        (df["estoque"] > 0) | positive_sales,
    ]
    choices = ["RUPTURA", "SEM GIRO", "FALTA", "EXCESSO", "ELEVADO", "ADEQUADO"]
    df["status"] = np.select(conditions, choices, default="SEM MOVIMENTO")

    if "data_entrada_mais_antiga" in df.columns:
        df["idade_estoque_dias"] = (
            reference_date - pd.to_datetime(df["data_entrada_mais_antiga"], errors="coerce")
        ).dt.days

    df["periodo_inicio"] = start_date
    df["periodo_fim"] = reference_date

    numeric_cols = [
        "estoque", "vendas_periodo", "estoque_ideal", "estoque_minimo",
        "estoque_maximo", "falta_qtd", "excesso_qtd"
    ]
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


def build_transfer_plan(model_detail: pd.DataFrame, color_detail: pd.DataFrame, cfg: AnalysisConfig) -> pd.DataFrame:
    """Plano de transferência em duas camadas.

    1) A necessidade e a disponibilidade são calculadas por loja + família + modelo.
    2) A cor é usada para escolher o mix a movimentar, sem criar necessidade adicional
       só porque uma cor teve poucas vendas no período.
    """
    if model_detail.empty:
        return pd.DataFrame()

    model = model_detail.reset_index(drop=True).copy()
    model["disponivel_transferencia"] = model.apply(lambda r: _availability_for_transfer(r, cfg), axis=1)
    model["necessidade_transferencia"] = model.apply(_need_for_transfer, axis=1)

    remaining_model_stock = model["estoque"].astype(float).to_dict()
    remaining_avail = model["disponivel_transferencia"].astype(int).to_dict()
    remaining_need = model["necessidade_transferencia"].astype(int).to_dict()

    # Estrutura de cor: preserva uma cobertura mínima aproximada no doador,
    # mas quem limita a quantidade total é o saldo do modelo.
    colors = color_detail.reset_index(drop=True).copy()
    colors["piso_cor"] = np.floor(colors["media_venda_dia"] * cfg.min_days).astype(int)
    colors["disp_cor"] = (colors["estoque"] - colors["piso_cor"]).clip(lower=0).astype(int)
    colors["need_cor"] = (
        np.ceil(colors["media_venda_dia"] * cfg.target_days) - colors["estoque"]
    ).clip(lower=0).astype(int)

    color_stock = {}
    color_avail = {}
    color_need = {}
    color_daily = {}
    color_cov = {}
    color_sales = {}
    for _, r in colors.iterrows():
        key = (r["regional"], r["loja"], r["familia"], r["modelo"], r["cor"])
        color_stock[key] = int(r["estoque"])
        color_avail[key] = int(r["disp_cor"])
        color_need[key] = int(r["need_cor"])
        color_daily[key] = float(r["media_venda_dia"])
        color_cov[key] = float(r["cobertura_dias"])
        color_sales[key] = int(r["vendas_periodo"])

    recipients = model[model["necessidade_transferencia"] > 0].copy()
    recipients["coverage_sort"] = recipients["cobertura_dias"].replace(np.inf, 10**9)
    recipients = recipients.sort_values(["coverage_sort", "media_venda_dia"], ascending=[True, False])
    transfers: list[dict] = []

    def recipient_color_order(rec) -> list[str]:
        subset = colors[
            colors["regional"].eq(rec["regional"])
            & colors["loja"].eq(rec["loja"])
            & colors["familia"].eq(rec["familia"])
            & colors["modelo"].eq(rec["modelo"])
        ].copy()
        if subset.empty:
            return []
        subset["need_sort"] = subset["need_cor"] > 0
        subset["cov_sort"] = subset["cobertura_dias"].replace(np.inf, 10**9)
        subset = subset.sort_values(
            ["need_sort", "cov_sort", "vendas_periodo"],
            ascending=[False, True, False],
        )
        return subset["cor"].tolist()

    def donor_color_order(donor) -> list[str]:
        subset = colors[
            colors["regional"].eq(donor["regional"])
            & colors["loja"].eq(donor["loja"])
            & colors["familia"].eq(donor["familia"])
            & colors["modelo"].eq(donor["modelo"])
        ].copy()
        if subset.empty:
            return []
        subset["key"] = list(zip(subset["regional"], subset["loja"], subset["familia"], subset["modelo"], subset["cor"]))
        subset["saldo_cor"] = subset["key"].map(lambda k: color_avail.get(k, 0))
        subset["cov_sort"] = subset["cobertura_dias"].replace(np.inf, 10**9)
        subset = subset[subset["saldo_cor"] > 0].sort_values(
            ["cov_sort", "saldo_cor", "vendas_periodo"], ascending=[False, False, True]
        )
        return subset["cor"].tolist()

    def record_transfer(ridx, didx, rec, donor, cor_origem, cor_ref, qty, exact):
        donor_before = remaining_model_stock[didx]
        rec_before = remaining_model_stock[ridx]
        donor_after = donor_before - qty
        rec_after = rec_before + qty
        transfers.append({
            "origem_regional": donor["regional"],
            "origem_loja": donor["loja"],
            "destino_regional": rec["regional"],
            "destino_loja": rec["loja"],
            "familia": rec["familia"],
            "modelo": rec["modelo"],
            "cor_origem": cor_origem,
            "cor_destino_referencia": cor_ref,
            "quantidade": int(qty),
            "tipo_pareamento": "EXATO" if exact else "COR ALTERNATIVA",
            "prioridade": "RECOMENDADA" if exact else "AVALIAR",
            "mesma_regional": "SIM" if donor["regional"] == rec["regional"] else "NAO",
            "cobertura_origem_antes": _coverage(donor_before, float(donor["media_venda_dia"])),
            "cobertura_origem_depois": _coverage(donor_after, float(donor["media_venda_dia"])),
            "cobertura_destino_antes": _coverage(rec_before, float(rec["media_venda_dia"])),
            "cobertura_destino_depois": _coverage(rec_after, float(rec["media_venda_dia"])),
            "venda_media_mes_destino": float(rec["media_venda_mes"]),
        })
        remaining_model_stock[didx] = donor_after
        remaining_model_stock[ridx] = rec_after
        remaining_avail[didx] -= qty
        remaining_need[ridx] -= qty

    def donor_candidates(rec):
        mask = (
            model["familia"].eq(rec["familia"])
            & model["modelo"].eq(rec["modelo"])
            & model["loja"].ne(rec["loja"])
        )
        donors = model.loc[mask].copy()
        donors = donors[[remaining_avail.get(i, 0) > 0 for i in donors.index]]
        if donors.empty:
            return donors
        donors["same_regional"] = donors["regional"].eq(rec["regional"])
        donors["coverage_sort"] = donors["cobertura_dias"].replace(np.inf, 10**9)
        sort_cols, ascending = [], []
        if cfg.prioritize_same_regional:
            sort_cols.append("same_regional")
            ascending.append(False)
        sort_cols += ["coverage_sort", "estoque"]
        ascending += [False, False]
        return donors.sort_values(sort_cols, ascending=ascending)

    # Passo 1: atender cores efetivamente demandadas no destino.
    for ridx, rec in recipients.iterrows():
        if remaining_need.get(ridx, 0) <= 0:
            continue
        preferred = recipient_color_order(rec)
        for didx, donor in donor_candidates(rec).iterrows():
            if remaining_need.get(ridx, 0) <= 0:
                break
            for cor in preferred:
                rec_key = (rec["regional"], rec["loja"], rec["familia"], rec["modelo"], cor)
                donor_key = (donor["regional"], donor["loja"], donor["familia"], donor["modelo"], cor)
                need_cor = color_need.get(rec_key, 0)
                avail_cor = color_avail.get(donor_key, 0)
                if need_cor <= 0 or avail_cor <= 0:
                    continue
                qty = min(remaining_need[ridx], remaining_avail[didx], need_cor, avail_cor)
                if qty <= 0:
                    continue
                record_transfer(ridx, didx, rec, donor, cor, cor, qty, True)
                color_need[rec_key] -= qty
                color_avail[donor_key] -= qty
                if remaining_avail.get(didx, 0) <= 0:
                    break

    # Passo 2: se ainda faltar modelo, oferece cor alternativa.
    if cfg.allow_flexible_color:
        for ridx, rec in recipients.iterrows():
            if remaining_need.get(ridx, 0) <= 0:
                continue
            preferred = recipient_color_order(rec)
            cor_ref = None
            for c in preferred:
                rkey = (rec["regional"], rec["loja"], rec["familia"], rec["modelo"], c)
                if color_need.get(rkey, 0) > 0:
                    cor_ref = c
                    break
            if cor_ref is None and preferred:
                cor_ref = preferred[0]
            if cor_ref is None:
                cor_ref = "MIX DO MODELO"

            for didx, donor in donor_candidates(rec).iterrows():
                if remaining_need.get(ridx, 0) <= 0:
                    break
                for cor in donor_color_order(donor):
                    donor_key = (donor["regional"], donor["loja"], donor["familia"], donor["modelo"], cor)
                    avail_cor = color_avail.get(donor_key, 0)
                    if avail_cor <= 0:
                        continue
                    qty = min(remaining_need[ridx], remaining_avail[didx], avail_cor)
                    if qty <= 0:
                        continue
                    record_transfer(ridx, didx, rec, donor, cor, cor_ref, qty, False)
                    color_avail[donor_key] -= qty
                    if remaining_avail.get(didx, 0) <= 0:
                        break

    return pd.DataFrame(transfers)
