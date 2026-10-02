from __future__ import annotations

from io import BytesIO
import pandas as pd
import numpy as np


def read_table(file_bytes: bytes, filename: str, sheet_name=None) -> pd.DataFrame:
    lower = filename.lower()
    bio = BytesIO(file_bytes)
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(bio, sheet_name=sheet_name if sheet_name is not None else 0)
    if lower.endswith(".csv"):
        return pd.read_csv(bio, sep=None, engine="python", encoding_errors="ignore")
    raise ValueError("Formato não suportado. Use XLSX, XLS, XLSM ou CSV.")


def excel_sheets(file_bytes: bytes, filename: str) -> list[str]:
    if filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return pd.ExcelFile(BytesIO(file_bytes)).sheet_names
    return []


def _safe_excel(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]) or pd.api.types.is_integer_dtype(out[col]):
            out[col] = out[col].replace([np.inf, -np.inf], np.nan)
    return out


def make_excel_report(sheets: dict[str, pd.DataFrame], params: dict) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter", datetime_format="dd/mm/yyyy", date_format="dd/mm/yyyy") as writer:
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#2B2B2B", "border": 0, "align": "center"})
        red_fmt = workbook.add_format({"bg_color": "#FDE8E8", "font_color": "#9B1C1C"})
        green_fmt = workbook.add_format({"bg_color": "#E7F6EC", "font_color": "#166534"})
        yellow_fmt = workbook.add_format({"bg_color": "#FFF7D6", "font_color": "#854D0E"})

        param_df = pd.DataFrame({"Parâmetro": list(params.keys()), "Valor": list(params.values())})
        param_df.to_excel(writer, sheet_name="Parametros", index=False)
        sheets_to_write = {"Parametros": param_df, **sheets}

        for name, df in sheets.items():
            safe = _safe_excel(df)
            safe.to_excel(writer, sheet_name=name[:31], index=False)

        for name, df in sheets_to_write.items():
            ws = writer.sheets[name[:31]]
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))
            for c, col in enumerate(df.columns):
                width = min(max(len(str(col)) + 2, 12), 32)
                if len(df):
                    # Mede somente valores realmente preenchidos. Em colunas vazias,
                    # quantile() pode retornar NaN e int(NaN) gera ValueError.
                    sample = df[col].dropna().astype(str).head(100)
                    if not sample.empty:
                        q90 = sample.str.len().quantile(0.9)
                        if pd.notna(q90):
                            width = min(max(width, int(q90) + 2), 32)
                ws.set_column(c, c, width)
                ws.write(0, c, col, header_fmt)

            if "status" in df.columns and len(df):
                idx = list(df.columns).index("status")
                col_letter = _xlsx_col(idx)
                rng = f"{col_letter}2:{col_letter}{len(df)+1}"
                ws.conditional_format(rng, {"type": "text", "criteria": "containing", "value": "RUPTURA", "format": red_fmt})
                ws.conditional_format(rng, {"type": "text", "criteria": "containing", "value": "FALTA", "format": red_fmt})
                ws.conditional_format(rng, {"type": "text", "criteria": "containing", "value": "EXCESSO", "format": yellow_fmt})
                ws.conditional_format(rng, {"type": "text", "criteria": "containing", "value": "SEM GIRO", "format": yellow_fmt})
                ws.conditional_format(rng, {"type": "text", "criteria": "containing", "value": "ADEQUADO", "format": green_fmt})

    return output.getvalue()


def _xlsx_col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s
