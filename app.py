from __future__ import annotations

import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st

from src.analysis import (
    AnalysisConfig,
    auto_pick,
    build_analysis,
    build_transfer_plan,
    coverage_display,
    infer_regional_from_stock,
    prepare_sales,
    prepare_stock,
)
from src.io_utils import excel_sheets, make_excel_report, read_table


st.set_page_config(page_title="Toyota | Gestão de Estoque", page_icon="🚘", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {background:#ffffff; border:1px solid #e5e7eb; padding:14px; border-radius:12px;}
    .app-title {font-size:2rem; font-weight:800; color:#202124; margin-bottom:0;}
    .app-subtitle {color:#6b7280; margin-top:0.1rem;}
    .badge {display:inline-block; background:#EB0A1E; color:white; padding:4px 10px; border-radius:999px; font-size:.8rem; font-weight:700;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<span class="badge">TOYOTA</span>', unsafe_allow_html=True)
st.markdown('<div class="app-title">Gestão Inteligente de Estoque</div>', unsafe_allow_html=True)
st.markdown('<div class="app-subtitle">Cobertura, excesso, ruptura e sugestões de transferência por regional, loja e veículo.</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Parâmetros")
    window_days = st.selectbox("Janela de vendas", [30, 60, 90, 120, 180], index=2, format_func=lambda x: f"Últimos {x} dias")
    min_days = st.number_input("Cobertura mínima (dias)", min_value=1, max_value=365, value=30)
    target_days = st.number_input("Cobertura alvo (dias)", min_value=1, max_value=365, value=45)
    max_days = st.number_input("Cobertura máxima (dias)", min_value=1, max_value=365, value=75)
    reserve_units = st.number_input("Reserva mínima no doador", min_value=0, max_value=20, value=1)
    prioritize_regional = st.checkbox("Priorizar transferências na mesma regional", value=True)
    flexible_color = st.checkbox("Permitir cor alternativa após tentativa exata", value=True)

    if not (min_days <= target_days <= max_days):
        st.error("Use: cobertura mínima ≤ alvo ≤ máxima.")

cfg = AnalysisConfig(
    window_days=int(window_days),
    min_days=int(min_days),
    target_days=int(target_days),
    max_days=int(max_days),
    reserve_units=int(reserve_units),
    prioritize_same_regional=prioritize_regional,
    allow_flexible_color=flexible_color,
)

st.subheader("1. Carregar bases")
c1, c2 = st.columns(2)
with c1:
    stock_file = st.file_uploader("Base de estoque", type=["xlsx", "xls", "xlsm", "csv"], key="stock")
with c2:
    sales_file = st.file_uploader("Base de vendas", type=["xlsx", "xls", "xlsm", "csv"], key="sales")

if not stock_file or not sales_file:
    st.info("Envie as duas bases para iniciar. Você pode testar com os arquivos da pasta `examples` do projeto.")
    st.stop()

stock_bytes = stock_file.getvalue()
sales_bytes = sales_file.getvalue()

stock_sheet = None
sales_sheet = None
stock_sheets = excel_sheets(stock_bytes, stock_file.name)
sales_sheets = excel_sheets(sales_bytes, sales_file.name)
if stock_sheets or sales_sheets:
    s1, s2 = st.columns(2)
    with s1:
        if stock_sheets:
            stock_sheet = st.selectbox("Aba do estoque", stock_sheets)
    with s2:
        if sales_sheets:
            sales_sheet = st.selectbox("Aba de vendas", sales_sheets)

try:
    stock_raw = read_table(stock_bytes, stock_file.name, stock_sheet)
    sales_raw = read_table(sales_bytes, sales_file.name, sales_sheet)
except Exception as exc:
    st.error(f"Erro ao ler os arquivos: {exc}")
    st.stop()

ALIASES = {
    "regional": ["regional", "regiao", "região", "regional vendas"],
    "loja": ["loja", "filial", "concessionaria", "concessionária", "empresa"],
    "familia": ["familia", "família", "linha", "familia modelo"],
    "modelo": ["modelo", "veiculo", "veículo", "modelo veiculo"],
    "versao": ["versao", "versão", "versao modelo", "grade"],
    "cor": ["cor", "cor externa", "cor exterior"],
    "quantidade": ["quantidade", "qtd", "qtde", "estoque", "volume"],
    "data_entrada": ["data entrada", "data faturamento", "data estoque", "entrada estoque"],
    "data": ["data venda", "data", "data faturamento", "dt venda"],
}


def mapping_select(label, columns, aliases, required=True, allow_each_line=False, allow_none=False):
    options = list(columns)
    special_each = "<cada linha = 1>"
    special_none = "<sem coluna>"
    if allow_each_line:
        options = [special_each] + options
    if allow_none:
        options = [special_none] + options
    guessed = auto_pick(columns, aliases)
    default_index = options.index(guessed) if guessed in options else 0
    value = st.selectbox(label, options, index=default_index)
    if value in {special_each, special_none}:
        return None
    return value

st.subheader("2. Mapear colunas")
map_tab1, map_tab2 = st.tabs(["Estoque", "Vendas"])
with map_tab1:
    cols = stock_raw.columns.tolist()
    a, b, c = st.columns(3)
    with a:
        stock_regional = mapping_select("Regional", cols, ALIASES["regional"], allow_none=True)
        stock_loja = mapping_select("Loja", cols, ALIASES["loja"])
        stock_familia = mapping_select("Família", cols, ALIASES["familia"])
    with b:
        stock_modelo = mapping_select("Modelo", cols, ALIASES["modelo"])
        stock_versao = mapping_select("Versão (opcional)", cols, ALIASES["versao"], allow_none=True)
        stock_cor = mapping_select("Cor", cols, ALIASES["cor"])
    with c:
        stock_qtd = mapping_select("Quantidade em estoque", cols, ALIASES["quantidade"], allow_each_line=True)
        stock_data_entrada = mapping_select("Data de entrada/faturamento (opcional)", cols, ALIASES["data_entrada"], allow_none=True)

with map_tab2:
    cols = sales_raw.columns.tolist()
    a, b, c = st.columns(3)
    with a:
        sales_regional = mapping_select("Regional", cols, ALIASES["regional"], allow_none=True)
        sales_loja = mapping_select("Loja", cols, ALIASES["loja"])
        sales_familia = mapping_select("Família", cols, ALIASES["familia"])
    with b:
        sales_modelo = mapping_select("Modelo", cols, ALIASES["modelo"])
        sales_versao = mapping_select("Versão (opcional)", cols, ALIASES["versao"], allow_none=True)
        sales_cor = mapping_select("Cor", cols, ALIASES["cor"])
    with c:
        sales_qtd = mapping_select("Quantidade vendida", cols, ALIASES["quantidade"], allow_each_line=True)
        sales_data = mapping_select("Data da venda", cols, ALIASES["data"])

stock_mapping = {
    "regional": stock_regional, "loja": stock_loja, "familia": stock_familia,
    "modelo": stock_modelo, "versao": stock_versao, "cor": stock_cor,
    "quantidade": stock_qtd, "data_entrada": stock_data_entrada,
}
sales_mapping = {
    "regional": sales_regional, "loja": sales_loja, "familia": sales_familia,
    "modelo": sales_modelo, "versao": sales_versao, "cor": sales_cor,
    "quantidade": sales_qtd, "data": sales_data,
}

try:
    stock = prepare_stock(stock_raw, stock_mapping)
    sales = prepare_sales(sales_raw, sales_mapping)
    sales = infer_regional_from_stock(stock, sales)
except Exception as exc:
    st.error(f"Não foi possível preparar as bases: {exc}")
    st.stop()

use_version = not (stock["versao"].eq("NAO INFORMADO").all() and sales["versao"].eq("NAO INFORMADO").all())

try:
    analysis_regional = build_analysis(stock, sales, ["regional"], cfg)
    analysis_loja = build_analysis(stock, sales, ["regional", "loja"], cfg)
    analysis_familia = build_analysis(stock, sales, ["familia"], cfg)
    analysis_modelo = build_analysis(stock, sales, ["familia", "modelo"] + (["versao"] if use_version else []), cfg)
    detail_cols = ["regional", "loja", "familia", "modelo"] + (["versao"] if use_version else []) + ["cor"]
    analysis_cor = build_analysis(stock, sales, ["familia", "modelo"] + (["versao"] if use_version else []) + ["cor"], cfg)
    detail = build_analysis(stock, sales, detail_cols, cfg)
    transfers = build_transfer_plan(detail, cfg, use_version=use_version)
except Exception as exc:
    st.error(f"Erro na análise: {exc}")
    st.stop()

# Filters
with st.sidebar:
    st.divider()
    st.subheader("Filtros")
    region_opts = sorted([x for x in detail["regional"].dropna().unique().tolist() if x != "NAO INFORMADO"])
    selected_regions = st.multiselect("Regional", region_opts, default=[])
    store_opts = sorted(detail.loc[detail["regional"].isin(selected_regions) if selected_regions else detail.index == detail.index, "loja"].dropna().unique().tolist())
    selected_stores = st.multiselect("Loja", store_opts, default=[])
    family_opts = sorted(detail["familia"].dropna().unique().tolist())
    selected_families = st.multiselect("Família", family_opts, default=[])

filtered_detail = detail.copy()
if selected_regions:
    filtered_detail = filtered_detail[filtered_detail["regional"].isin(selected_regions)]
if selected_stores:
    filtered_detail = filtered_detail[filtered_detail["loja"].isin(selected_stores)]
if selected_families:
    filtered_detail = filtered_detail[filtered_detail["familia"].isin(selected_families)]

# Dashboard KPIs
st.subheader("3. Painel executivo")
cols = st.columns(5)
cols[0].metric("Estoque", f"{int(filtered_detail['estoque'].sum()):,}".replace(",", "."))
cols[1].metric(f"Vendas {cfg.window_days}d", f"{int(filtered_detail['vendas_periodo'].sum()):,}".replace(",", "."))
cols[2].metric("Excesso potencial", f"{int(filtered_detail['excesso_qtd'].sum()):,}".replace(",", "."))
cols[3].metric("Falta até alvo", f"{int(filtered_detail['falta_qtd'].sum()):,}".replace(",", "."))
cols[4].metric("Transferências sugeridas", f"{int(transfers['quantidade'].sum()) if not transfers.empty else 0:,}".replace(",", "."))

status_counts = filtered_detail.groupby("status", as_index=False)["estoque"].sum()
if not status_counts.empty:
    fig = px.bar(status_counts, x="status", y="estoque", text_auto=True, title="Distribuição do estoque por status")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=50, b=10), xaxis_title="", yaxis_title="Estoque")
    st.plotly_chart(fig, use_container_width=True)

# Main tabs
tabs = st.tabs(["Loja", "Veículo", "Excesso", "Falta", "Transferências", "Exportar"])

with tabs[0]:
    st.markdown("#### Consolidado por regional")
    regional_view = analysis_regional.copy()
    regional_view["cobertura"] = regional_view["cobertura_dias"].map(coverage_display)
    st.dataframe(regional_view.drop(columns=["cobertura_dias", "media_venda_dia"], errors="ignore"), use_container_width=True, hide_index=True)

    st.markdown("#### Consolidado por loja")
    loja_view = analysis_loja.copy()
    loja_view["cobertura"] = loja_view["cobertura_dias"].map(coverage_display)
    st.dataframe(loja_view.drop(columns=["cobertura_dias", "media_venda_dia"], errors="ignore"), use_container_width=True, hide_index=True)

with tabs[1]:
    level = st.radio("Nível", ["Família", "Modelo", "Cor"], horizontal=True)
    vehicle_df = {"Família": analysis_familia, "Modelo": analysis_modelo, "Cor": analysis_cor}[level].copy()
    vehicle_df["cobertura"] = vehicle_df["cobertura_dias"].map(coverage_display)
    st.dataframe(vehicle_df.drop(columns=["cobertura_dias", "media_venda_dia"], errors="ignore"), use_container_width=True, hide_index=True)

with tabs[2]:
    excess = filtered_detail[filtered_detail["status"].isin(["EXCESSO", "SEM GIRO"])].copy()
    excess = excess.sort_values(["excesso_qtd", "estoque"], ascending=False)
    excess["cobertura"] = excess["cobertura_dias"].map(coverage_display)
    st.dataframe(excess.drop(columns=["cobertura_dias", "media_venda_dia"], errors="ignore"), use_container_width=True, hide_index=True)

with tabs[3]:
    shortage = filtered_detail[filtered_detail["status"].isin(["RUPTURA", "FALTA"])].copy()
    shortage = shortage.sort_values(["falta_qtd", "media_venda_mes"], ascending=[False, False])
    shortage["cobertura"] = shortage["cobertura_dias"].map(coverage_display)
    st.dataframe(shortage.drop(columns=["cobertura_dias", "media_venda_dia"], errors="ignore"), use_container_width=True, hide_index=True)

with tabs[4]:
    if transfers.empty:
        st.info("Nenhuma transferência foi sugerida com os parâmetros atuais.")
    else:
        transfer_view = transfers.copy()
        for col in ["cobertura_origem_antes", "cobertura_origem_depois", "cobertura_destino_antes", "cobertura_destino_depois"]:
            transfer_view[col] = transfer_view[col].map(coverage_display)
        st.dataframe(transfer_view, use_container_width=True, hide_index=True)
        exact_units = int(transfers.loc[transfers["tipo_pareamento"] == "EXATO", "quantidade"].sum()) if "tipo_pareamento" in transfers else 0
        flex_units = int(transfers.loc[transfers["tipo_pareamento"] == "COR FLEXIVEL", "quantidade"].sum()) if "tipo_pareamento" in transfers else 0
        st.caption(f"Transferências exatas: {exact_units} un. | Oportunidades com cor alternativa: {flex_units} un.")

with tabs[5]:
    excess_export = detail[detail["status"].isin(["EXCESSO", "SEM GIRO"])].copy()
    shortage_export = detail[detail["status"].isin(["RUPTURA", "FALTA"])].copy()
    report_sheets = {
        "Loja_Regional": analysis_regional,
        "Loja_Detalhe": analysis_loja,
        "Veiculo_Familia": analysis_familia,
        "Veiculo_Modelo": analysis_modelo,
        "Veiculo_Cor": analysis_cor,
        "Excesso": excess_export,
        "Falta": shortage_export,
        "Transferencias": transfers,
    }
    params = {
        "Janela de vendas (dias)": cfg.window_days,
        "Cobertura mínima (dias)": cfg.min_days,
        "Cobertura alvo (dias)": cfg.target_days,
        "Cobertura máxima (dias)": cfg.max_days,
        "Reserva mínima no doador": cfg.reserve_units,
        "Priorizar mesma regional": "Sim" if cfg.prioritize_same_regional else "Não",
        "Permitir cor alternativa": "Sim" if cfg.allow_flexible_color else "Não",
    }
    excel_bytes = make_excel_report(report_sheets, params)
    st.download_button(
        "Baixar relatório Excel completo",
        data=excel_bytes,
        file_name="analise_estoque_toyota.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.caption("O relatório contém parâmetros, consolidado por regional/loja, família/modelo/cor, excesso, falta e transferências.")
