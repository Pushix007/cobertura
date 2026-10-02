from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src.analysis import (
    AnalysisConfig,
    auto_pick,
    build_analysis,
    build_transfer_plan,
    coverage_display,
    filter_sales_window,
    infer_regional_from_stock,
    prepare_sales,
    prepare_stock,
    sales_period,
)
from src.io_utils import excel_sheets, make_excel_report, read_table


st.set_page_config(page_title="Toyota | Gestão de Estoque", page_icon="🚘", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.1rem; padding-bottom: 2rem;}
    [data-testid="stMetric"] {background:#ffffff; border:1px solid #e5e7eb; padding:14px; border-radius:12px;}
    [data-testid="stMetricLabel"],
    [data-testid="stMetricLabel"] p {color:#374151 !important; opacity:1 !important;}
    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] div {color:#111827 !important;}
    [data-testid="stMetricDelta"] {color:#374151 !important;}
    .app-title {font-size:2rem; font-weight:800; color:#f8fafc; margin-bottom:0;}
    .app-subtitle {color:#94a3b8; margin-top:0.1rem;}
    .badge {display:inline-block; background:#EB0A1E; color:white; padding:4px 10px; border-radius:999px; font-size:.8rem; font-weight:700;}
    .okbox {padding:.8rem 1rem; border-radius:10px; background:#ecfdf5; color:#166534; border:1px solid #bbf7d0;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<span class="badge">TOYOTA</span>', unsafe_allow_html=True)
st.markdown('<div class="app-title">Gestão Inteligente de Estoque</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="app-subtitle">Cobertura, excesso, ruptura e transferências por regional, loja, família, modelo e cor.</div>',
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Upload e leitura
# -----------------------------------------------------------------------------
st.subheader("1. Carregar bases")
c1, c2 = st.columns(2)
with c1:
    stock_file = st.file_uploader("Base de estoque", type=["xlsx", "xls", "xlsm", "csv"], key="stock")
with c2:
    sales_file = st.file_uploader("Histórico de vendas", type=["xlsx", "xls", "xlsm", "csv"], key="sales")

if not stock_file or not sales_file:
    st.info("Envie a base de estoque e o histórico de vendas para iniciar a análise.")
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

# -----------------------------------------------------------------------------
# Perfil Toyota real + fallback para mapeamento manual
# -----------------------------------------------------------------------------
TOYOTA_STOCK_COLUMNS = {"Regional", "Filial", "Pátio", "Familia", "Modelo", "Cor", "Chassi"}
TOYOTA_SALES_COLUMNS = {"Regional", "Filial_vendedor", "Familia", "Modelo", "Cor", "Chassi", "Data Venda"}
recognized_toyota = TOYOTA_STOCK_COLUMNS.issubset(set(stock_raw.columns)) and TOYOTA_SALES_COLUMNS.issubset(set(sales_raw.columns))

ALIASES = {
    "regional": ["regional", "regiao", "região", "regional vendas"],
    "loja": ["loja", "filial", "filial vendedor", "concessionaria", "concessionária", "empresa"],
    "patio": ["patio", "pátio", "local estoque", "localizacao", "localização"],
    "familia": ["familia", "família", "linha", "familia modelo"],
    "modelo": ["modelo", "veiculo", "veículo", "modelo veiculo"],
    "cor": ["cor", "cor externa", "cor exterior"],
    "chassi": ["chassi", "vin"],
    "quantidade": ["quantidade", "qtd", "qtde", "estoque", "volume"],
    "data_entrada": ["data entrada", "data faturamento", "data estoque", "entrada estoque"],
    "data": ["data venda", "data", "data faturamento", "dt venda"],
}


def mapping_select(label, columns, aliases, allow_each_line=False, allow_none=False, key=None):
    options = list(columns)
    special_each = "<cada linha = 1>"
    special_none = "<sem coluna>"
    if allow_each_line:
        options = [special_each] + options
    if allow_none:
        options = [special_none] + options
    guessed = auto_pick(columns, aliases)
    default_index = options.index(guessed) if guessed in options else 0
    value = st.selectbox(label, options, index=default_index, key=key)
    if value in {special_each, special_none}:
        return None
    return value


if recognized_toyota:
    st.markdown(
        '<div class="okbox"><b>Formato Toyota reconhecido.</b> O sistema identificou automaticamente Regional, Filial, Pátio, Família, Modelo, Cor, Chassi e Data Venda.</div>',
        unsafe_allow_html=True,
    )
    stock_mapping = {
        "regional": "Regional", "loja": "Filial", "patio": "Pátio", "familia": "Familia",
        "modelo": "Modelo", "cor": "Cor", "chassi": "Chassi", "quantidade": None, "data_entrada": None,
    }
    sales_mapping = {
        "regional": "Regional", "loja": "Filial_vendedor", "familia": "Familia", "modelo": "Modelo",
        "cor": "Cor", "chassi": "Chassi", "quantidade": None, "data": "Data Venda",
    }
else:
    st.warning("O layout não corresponde exatamente ao padrão Toyota conhecido. Confirme o mapeamento abaixo.")
    with st.expander("Mapeamento de colunas", expanded=True):
        map_tab1, map_tab2 = st.tabs(["Estoque", "Vendas"])
        with map_tab1:
            cols = stock_raw.columns.tolist()
            a, b, c = st.columns(3)
            with a:
                stock_regional = mapping_select("Regional", cols, ALIASES["regional"], allow_none=True, key="s_reg")
                stock_loja = mapping_select("Loja", cols, ALIASES["loja"], key="s_loja")
                stock_patio = mapping_select("Pátio (opcional)", cols, ALIASES["patio"], allow_none=True, key="s_patio")
            with b:
                stock_familia = mapping_select("Família", cols, ALIASES["familia"], key="s_fam")
                stock_modelo = mapping_select("Modelo", cols, ALIASES["modelo"], key="s_mod")
                stock_cor = mapping_select("Cor", cols, ALIASES["cor"], key="s_cor")
            with c:
                stock_chassi = mapping_select("Chassi (opcional)", cols, ALIASES["chassi"], allow_none=True, key="s_chassi")
                stock_qtd = mapping_select("Quantidade", cols, ALIASES["quantidade"], allow_each_line=True, key="s_qtd")
                stock_data_entrada = mapping_select("Data de entrada (opcional)", cols, ALIASES["data_entrada"], allow_none=True, key="s_dt")
        with map_tab2:
            cols = sales_raw.columns.tolist()
            a, b, c = st.columns(3)
            with a:
                sales_regional = mapping_select("Regional", cols, ALIASES["regional"], allow_none=True, key="v_reg")
                sales_loja = mapping_select("Loja", cols, ALIASES["loja"], key="v_loja")
                sales_data = mapping_select("Data da venda", cols, ALIASES["data"], key="v_data")
            with b:
                sales_familia = mapping_select("Família", cols, ALIASES["familia"], key="v_fam")
                sales_modelo = mapping_select("Modelo", cols, ALIASES["modelo"], key="v_mod")
                sales_cor = mapping_select("Cor", cols, ALIASES["cor"], key="v_cor")
            with c:
                sales_chassi = mapping_select("Chassi (opcional)", cols, ALIASES["chassi"], allow_none=True, key="v_chassi")
                sales_qtd = mapping_select("Quantidade vendida", cols, ALIASES["quantidade"], allow_each_line=True, key="v_qtd")
        stock_mapping = {
            "regional": stock_regional, "loja": stock_loja, "patio": stock_patio, "familia": stock_familia,
            "modelo": stock_modelo, "cor": stock_cor, "chassi": stock_chassi,
            "quantidade": stock_qtd, "data_entrada": stock_data_entrada,
        }
        sales_mapping = {
            "regional": sales_regional, "loja": sales_loja, "familia": sales_familia, "modelo": sales_modelo,
            "cor": sales_cor, "chassi": sales_chassi, "quantidade": sales_qtd, "data": sales_data,
        }

try:
    stock_prepared = prepare_stock(stock_raw, stock_mapping)
    sales_prepared = prepare_sales(sales_raw, sales_mapping)
    sales_prepared = infer_regional_from_stock(stock_prepared, sales_prepared)
except Exception as exc:
    st.error(f"Não foi possível preparar as bases: {exc}")
    st.stop()

# -----------------------------------------------------------------------------
# Parâmetros e regras operacionais
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("Parâmetros")
    window_label = st.selectbox(
        "Período de vendas",
        ["Período completo da base", "Últimos 30 dias", "Últimos 60 dias", "Últimos 90 dias", "Últimos 120 dias", "Últimos 180 dias"],
        index=0,
    )
    window_map = {
        "Período completo da base": None,
        "Últimos 30 dias": 30, "Últimos 60 dias": 60, "Últimos 90 dias": 90,
        "Últimos 120 dias": 120, "Últimos 180 dias": 180,
    }
    window_days = window_map[window_label]
    min_days = st.number_input("Cobertura mínima (dias)", min_value=1, max_value=365, value=30)
    target_days = st.number_input("Cobertura alvo (dias)", min_value=1, max_value=365, value=45)
    max_days = st.number_input("Cobertura máxima (dias)", min_value=1, max_value=365, value=75)
    reserve_units = st.number_input("Reserva mínima no doador", min_value=0, max_value=20, value=1)
    prioritize_regional = st.checkbox("Priorizar mesma regional", value=True)
    flexible_color = st.checkbox("Sugerir cor alternativa", value=True)

    st.divider()
    st.subheader("Estoque elegível")
    patio_opts = sorted(x for x in stock_prepared["patio"].dropna().unique().tolist() if x != "NAO INFORMADO")
    default_excluded = [x for x in ["DEMONSTRACAO"] if x in patio_opts]
    excluded_patios = st.multiselect("Excluir pátios/status", patio_opts, default=default_excluded)

    brand_opts = sorted(set(stock_prepared["marca"].unique()).union(set(sales_prepared["marca"].unique())))
    selected_brands = st.multiselect("Marca", brand_opts, default=brand_opts)

    if not (min_days <= target_days <= max_days):
        st.error("Use: cobertura mínima ≤ alvo ≤ máxima.")
    if not selected_brands:
        st.error("Selecione ao menos uma marca.")

if not selected_brands or not (min_days <= target_days <= max_days):
    st.stop()

cfg = AnalysisConfig(
    window_days=window_days,
    min_days=int(min_days), target_days=int(target_days), max_days=int(max_days),
    reserve_units=int(reserve_units), prioritize_same_regional=prioritize_regional,
    allow_flexible_color=flexible_color,
)

stock = stock_prepared[stock_prepared["marca"].isin(selected_brands)].copy()
if excluded_patios:
    stock = stock[~stock["patio"].isin(excluded_patios)].copy()
sales = sales_prepared[sales_prepared["marca"].isin(selected_brands)].copy()

if sales.empty:
    st.error("Não há vendas após os filtros selecionados.")
    st.stop()

try:
    start_date, end_date, effective_days = sales_period(sales, cfg.window_days)
    sales_window, _, _, _ = filter_sales_window(sales, cfg.window_days)
    analysis_regional = build_analysis(stock, sales, ["regional"], cfg)
    analysis_loja = build_analysis(stock, sales, ["regional", "loja"], cfg)
    analysis_familia = build_analysis(stock, sales, ["familia"], cfg)
    analysis_modelo = build_analysis(stock, sales, ["familia", "modelo"], cfg)
    analysis_cor = build_analysis(stock, sales, ["familia", "modelo", "cor"], cfg)
    detail_model = build_analysis(stock, sales, ["regional", "loja", "familia", "modelo"], cfg)
    detail_color = build_analysis(stock, sales, ["regional", "loja", "familia", "modelo", "cor"], cfg)
    transfers = build_transfer_plan(detail_model, detail_color, cfg)
except Exception as exc:
    st.error(f"Erro na análise: {exc}")
    st.stop()

st.caption(
    f"Período considerado: **{start_date:%d/%m/%Y} a {end_date:%d/%m/%Y}** ({effective_days} dias). "
    f"Famílias com prefixo `TOY` são normalizadas automaticamente."
)

# -----------------------------------------------------------------------------
# Filtros de visualização
# -----------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.subheader("Filtros de visualização")
    region_opts = sorted(x for x in detail_model["regional"].dropna().unique().tolist() if x != "NAO INFORMADO")
    selected_regions = st.multiselect("Regional", region_opts, default=[])
    store_base = detail_model[detail_model["regional"].isin(selected_regions)] if selected_regions else detail_model
    store_opts = sorted(x for x in store_base["loja"].dropna().unique().tolist() if x != "NAO INFORMADO")
    selected_stores = st.multiselect("Loja", store_opts, default=[])
    family_opts = sorted(detail_model["familia"].dropna().unique().tolist())
    selected_families = st.multiselect("Família", family_opts, default=[])


def apply_detail_filters(df):
    out = df.copy()
    if selected_regions and "regional" in out.columns:
        out = out[out["regional"].isin(selected_regions)]
    if selected_stores and "loja" in out.columns:
        out = out[out["loja"].isin(selected_stores)]
    if selected_families and "familia" in out.columns:
        out = out[out["familia"].isin(selected_families)]
    return out


def pretty_df(df: pd.DataFrame, coverage_text=True) -> pd.DataFrame:
    out = df.copy()
    if coverage_text and "cobertura_dias" in out.columns:
        out["Cobertura"] = out["cobertura_dias"].map(coverage_display)
    rename = {
        "regional": "Regional", "loja": "Loja", "familia": "Família", "modelo": "Modelo", "cor": "Cor",
        "estoque": "Estoque", "vendas_periodo": "Vendas período", "media_venda_mes": "Média venda/mês",
        "estoque_ideal": "Estoque alvo", "estoque_minimo": "Estoque mínimo", "estoque_maximo": "Estoque máximo",
        "falta_qtd": "Falta até alvo", "excesso_qtd": "Excesso transferível", "status": "Status",
        "periodo_dias": "Dias analisados",
    }
    out = out.rename(columns=rename)
    drop_cols = [
        "cobertura_dias", "media_venda_dia", "data_entrada_media", "data_entrada_mais_antiga",
        "idade_estoque_dias", "periodo_inicio", "periodo_fim"
    ]
    return out.drop(columns=[c for c in drop_cols if c in out.columns], errors="ignore")


filtered_detail = apply_detail_filters(detail_model)
filtered_transfers = transfers.copy()
if not filtered_transfers.empty:
    if selected_regions:
        filtered_transfers = filtered_transfers[filtered_transfers["destino_regional"].isin(selected_regions)]
    if selected_stores:
        filtered_transfers = filtered_transfers[filtered_transfers["destino_loja"].isin(selected_stores)]
    if selected_families:
        filtered_transfers = filtered_transfers[filtered_transfers["familia"].isin(selected_families)]

# -----------------------------------------------------------------------------
# Painel executivo
# -----------------------------------------------------------------------------
st.subheader("2. Painel executivo")
stock_total = int(filtered_detail["estoque"].sum())
sales_total = int(filtered_detail["vendas_periodo"].sum())
daily_total = float(filtered_detail["media_venda_dia"].sum())
weighted_coverage = stock_total / daily_total if daily_total > 0 else np.inf
excess_total = int(filtered_detail["excesso_qtd"].sum())
shortage_total = int(filtered_detail["falta_qtd"].sum())
transfer_total = int(filtered_transfers["quantidade"].sum()) if not filtered_transfers.empty else 0

k = st.columns(6)
k[0].metric("Estoque elegível", f"{stock_total:,}".replace(",", "."))
k[1].metric("Vendas no período", f"{sales_total:,}".replace(",", "."))
k[2].metric("Cobertura consolidada", coverage_display(weighted_coverage))
k[3].metric("Excesso transferível", f"{excess_total:,}".replace(",", "."))
k[4].metric("Falta até alvo", f"{shortage_total:,}".replace(",", "."))
k[5].metric("Transferências sugeridas", f"{transfer_total:,}".replace(",", "."))

raw_stock_units = int(stock_prepared.loc[stock_prepared["marca"].isin(selected_brands), "estoque"].sum())
excluded_units = raw_stock_units - int(stock["estoque"].sum())
transit_units = int(stock.loc[stock["patio"].eq("TRANSITO"), "estoque"].sum()) if "TRANSITO" in set(stock["patio"]) else 0
st.caption(
    f"Estoque informado nas marcas selecionadas: **{raw_stock_units:,}** | "
    f"Excluído pelos pátios/status: **{excluded_units:,}** | Em trânsito dentro do estoque elegível: **{transit_units:,}**".replace(",", ".")
)

chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    status_counts = filtered_detail.groupby("status", as_index=False)["estoque"].sum()
    fig = px.bar(status_counts, x="status", y="estoque", text_auto=True, title="Estoque por situação")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=50, b=10), xaxis_title="", yaxis_title="Veículos")
    st.plotly_chart(fig, use_container_width=True)
with chart_col2:
    regional_chart = analysis_regional.copy()
    if selected_regions:
        regional_chart = regional_chart[regional_chart["regional"].isin(selected_regions)]
    regional_chart["cobertura_plot"] = regional_chart["cobertura_dias"].replace(np.inf, np.nan)
    fig2 = px.bar(regional_chart, x="regional", y="cobertura_plot", text_auto=".0f", title="Cobertura por regional")
    fig2.add_hline(y=cfg.target_days, line_dash="dash", annotation_text=f"Alvo {cfg.target_days}d")
    fig2.update_layout(height=340, margin=dict(l=10, r=10, t=50, b=10), xaxis_title="", yaxis_title="Dias")
    st.plotly_chart(fig2, use_container_width=True)

# -----------------------------------------------------------------------------
# Abas
# -----------------------------------------------------------------------------
tabs = st.tabs(["Loja", "Veículo", "Excesso", "Falta", "Transferências", "Qualidade da base", "Exportar"])

with tabs[0]:
    st.markdown("#### Consolidado por regional")
    regional_view = analysis_regional.copy()
    if selected_regions:
        regional_view = regional_view[regional_view["regional"].isin(selected_regions)]
    st.dataframe(pretty_df(regional_view), use_container_width=True, hide_index=True)

    st.markdown("#### Consolidado por loja")
    loja_view = apply_detail_filters(analysis_loja)
    st.dataframe(pretty_df(loja_view), use_container_width=True, hide_index=True)

with tabs[1]:
    level = st.radio("Nível de análise", ["Família", "Modelo", "Cor"], horizontal=True)
    vehicle_df = {"Família": analysis_familia, "Modelo": analysis_modelo, "Cor": analysis_cor}[level].copy()
    if selected_families and "familia" in vehicle_df.columns:
        vehicle_df = vehicle_df[vehicle_df["familia"].isin(selected_families)]
    st.dataframe(pretty_df(vehicle_df), use_container_width=True, hide_index=True)
    st.caption("No arquivo Toyota recebido, o campo **Modelo** já representa a configuração/versão comercial completa do veículo.")

with tabs[2]:
    crit_level = st.radio("Detalhamento do excesso", ["Modelo", "Cor"], horizontal=True, key="excess_level")
    excess_base = filtered_detail if crit_level == "Modelo" else apply_detail_filters(detail_color)
    excess = excess_base[excess_base["status"].isin(["EXCESSO", "SEM GIRO"])].copy()
    excess = excess.sort_values(["excesso_qtd", "estoque"], ascending=False)
    st.dataframe(pretty_df(excess), use_container_width=True, hide_index=True)

with tabs[3]:
    crit_level = st.radio("Detalhamento da falta", ["Modelo", "Cor"], horizontal=True, key="shortage_level")
    shortage_base = filtered_detail if crit_level == "Modelo" else apply_detail_filters(detail_color)
    shortage = shortage_base[shortage_base["status"].isin(["RUPTURA", "FALTA"])].copy()
    shortage = shortage.sort_values(["falta_qtd", "media_venda_mes"], ascending=[False, False])
    st.dataframe(pretty_df(shortage), use_container_width=True, hide_index=True)

with tabs[4]:
    if filtered_transfers.empty:
        st.info("Nenhuma transferência foi sugerida com os parâmetros e filtros atuais.")
    else:
        transfer_view = filtered_transfers.copy()
        for col in ["cobertura_origem_antes", "cobertura_origem_depois", "cobertura_destino_antes", "cobertura_destino_depois"]:
            transfer_view[col] = transfer_view[col].map(coverage_display)
        transfer_view = transfer_view.rename(columns={
            "origem_regional": "Regional origem", "origem_loja": "Loja origem",
            "destino_regional": "Regional destino", "destino_loja": "Loja destino",
            "familia": "Família", "modelo": "Modelo", "cor_origem": "Cor origem",
            "cor_destino_referencia": "Cor demandada", "quantidade": "Quantidade",
            "tipo_pareamento": "Pareamento", "prioridade": "Prioridade", "mesma_regional": "Mesma regional",
            "cobertura_origem_antes": "Cob. origem antes", "cobertura_origem_depois": "Cob. origem depois",
            "cobertura_destino_antes": "Cob. destino antes", "cobertura_destino_depois": "Cob. destino depois",
            "venda_media_mes_destino": "Média venda/mês destino",
        })
        st.dataframe(transfer_view, use_container_width=True, hide_index=True)
        exact_units = int(filtered_transfers.loc[filtered_transfers["tipo_pareamento"] == "EXATO", "quantidade"].sum())
        flex_units = int(filtered_transfers.loc[filtered_transfers["tipo_pareamento"] == "COR ALTERNATIVA", "quantidade"].sum())
        st.caption(f"Recomendações exatas: **{exact_units} un.** | Oportunidades para avaliar outra cor: **{flex_units} un.**")

with tabs[5]:
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Linhas estoque recebidas", f"{len(stock_raw):,}".replace(",", "."))
    q2.metric("Linhas vendas recebidas", f"{len(sales_raw):,}".replace(",", "."))
    q3.metric("Estoque após deduplicação", f"{len(stock_prepared):,}".replace(",", "."))
    q4.metric("Vendas após deduplicação", f"{len(sales_prepared):,}".replace(",", "."))

    normalized_stock = int((stock_prepared["familia_original"] != stock_prepared["familia"]).sum())
    normalized_sales = int((sales_prepared["familia_original"] != sales_prepared["familia"]).sum())
    st.write(f"**Normalização de família:** {normalized_stock} linhas do estoque e {normalized_sales} linhas de vendas tiveram o prefixo `TOY` unificado.")

    stock_stores = set(stock["loja"].unique())
    sales_stores = set(sales_window["loja"].unique())
    sales_only = sorted(sales_stores - stock_stores)
    if sales_only:
        st.warning(
            "Existem lojas com vendas no período e sem estoque elegível atual. Elas são mantidas na análise com estoque zero, "
            "o que permite sinalizar ruptura/falta: " + ", ".join(sales_only)
        )
    else:
        st.success("Todas as lojas com vendas no período possuem estoque elegível atual.")

    if recognized_toyota:
        st.success("Estrutura dos dois arquivos compatível com o padrão Toyota utilizado nesta versão do sistema.")

with tabs[6]:
    excess_export = detail_model[detail_model["status"].isin(["EXCESSO", "SEM GIRO"])].copy()
    shortage_export = detail_model[detail_model["status"].isin(["RUPTURA", "FALTA"])].copy()
    report_sheets = {
        "Loja_Regional": analysis_regional,
        "Loja_Detalhe": analysis_loja,
        "Loja_Modelo": detail_model,
        "Loja_Modelo_Cor": detail_color,
        "Veiculo_Familia": analysis_familia,
        "Veiculo_Modelo": analysis_modelo,
        "Veiculo_Cor": analysis_cor,
        "Excesso_Modelo": excess_export,
        "Falta_Modelo": shortage_export,
        "Transferencias": transfers,
    }
    params = {
        "Período de vendas": f"{start_date:%d/%m/%Y} a {end_date:%d/%m/%Y}",
        "Dias efetivos analisados": effective_days,
        "Cobertura mínima (dias)": cfg.min_days,
        "Cobertura alvo (dias)": cfg.target_days,
        "Cobertura máxima (dias)": cfg.max_days,
        "Reserva mínima no doador": cfg.reserve_units,
        "Priorizar mesma regional": "Sim" if cfg.prioritize_same_regional else "Não",
        "Permitir cor alternativa": "Sim" if cfg.allow_flexible_color else "Não",
        "Pátios/status excluídos": ", ".join(excluded_patios) if excluded_patios else "Nenhum",
        "Marcas": ", ".join(selected_brands),
    }
    try:
        excel_bytes = make_excel_report(report_sheets, params)
    except Exception as exc:
        st.error(
            "Não foi possível gerar o arquivo Excel neste momento. "
            "As análises na tela continuam disponíveis. "
            f"Detalhe técnico: {type(exc).__name__}: {exc}"
        )
    else:
        st.download_button(
            "Baixar relatório Excel completo",
            data=excel_bytes,
            file_name="analise_estoque_toyota.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.caption("O relatório reflete os parâmetros de negócio, marcas e pátios/status selecionados acima.")
