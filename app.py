"""
Split Payments — Reporte Interactivo de Aperturas
7 tabs: Resumen, KAMs, Empresas, Segmentos, Mensajes P2/P3, Alertas, Conclusiones
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_loader import load_campaign_data
from segmentation import SEGMENTS, aggregate_to_accounts, get_kam_summary, get_segment_counts
from hubspot_lists import create_all_segment_lists

# ── Brand ─────────────────────────────────────────────────────────────────────

BRAND = {
    "primary": "#266D6C",
    "dark":    "#212121",
    "accent":  "#518A89",
    "bg":      "#F1F0EC",
    "light":   "#E4F0EF",
}

EXPORTS_DIR = Path(__file__).parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

# ── Plantillas de mensajes P2 / P3 ───────────────────────────────────────────

MSG_SUBJECT = "El monto de tus pagos ya no determina su velocidad, {empresa}"

MSG_BODY = """Hola {nombre},

Te escribo para retomar el correo que te envié hace unos días sobre Split Payments.

Con Split Payments puedes dividir automáticamente cualquier transferencia que exceda el límite de monto del riel en las transacciones necesarias, para que se ejecute completamente en menos de 20 segundos a cualquier banco, sin caer a rieles más lentos, ni intervención manual.

Así funciona:

→ Tú envías un solo pago por el monto total. Cobre lo divide en las transacciones que el riel permite y las procesa todas en tiempo real.

→ Un pago de 50M COP, por ejemplo, se convierte en 5 transacciones por Bre-B — automáticamente.

¿Lo activamos para {empresa}? Puedes responder este correo o escribirme directamente.

{kam}
Cobre"""

MSG_HTML_PREVIEW = """
<div style="max-width:460px;font-family:sans-serif;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
  <div style="background:#f8f7f3;padding:1.2rem;text-align:center;border-bottom:1px solid #e0e0e0;">
    <span style="font-weight:700;font-size:1rem;letter-spacing:1px;">⋮⋮ Cobre</span>
  </div>
  <div style="padding:1.5rem 1.8rem;">
    <h2 style="font-size:1.4rem;font-weight:700;line-height:1.3;margin:0 0 0.8rem;">
      El monto de tus pagos ya no determina su velocidad.
    </h2>
    <p style="color:#555;font-size:0.9rem;margin:0 0 1.2rem;">
      Ahora puedes enviar pagos que superen el tope de Bre-B y que sigan viajando por el riel más rápido.
    </p>
  </div>
  <div style="background:#1a1a1a;color:white;padding:1.5rem 1.8rem;">
    <p style="font-size:0.85rem;margin:0 0 1rem;line-height:1.6;">
      Hola <b>{nombre}</b>,<br><br>
      Te escribo para retomar el correo que te envié hace unos días sobre Split Payments.<br><br>
      Con Split Payments puedes dividir automáticamente cualquier transferencia que exceda el límite de monto del riel, para que se ejecute en menos de 20 segundos a cualquier banco — sin caer a rieles más lentos.
    </p>
    <p style="font-size:0.85rem;font-weight:700;margin:1rem 0 0.5rem;">Así funciona:</p>
    <p style="font-size:0.85rem;margin:0 0 0.4rem;">→ Tú envías un solo pago por el monto total. Cobre lo divide y procesa todo en tiempo real.</p>
    <p style="font-size:0.85rem;margin:0;">→ Un pago de 50M COP se convierte en 5 transacciones por Bre-B — automáticamente.</p>
  </div>
  <div style="padding:1.2rem 1.8rem;text-align:center;border-top:1px solid #e0e0e0;">
    <div style="display:inline-block;background:#266D6C;color:white;padding:0.7rem 1.5rem;border-radius:6px;font-size:0.88rem;font-weight:600;">
      Actívalo con tu Gerente de Cuenta →
    </div>
    <p style="color:#888;font-size:0.8rem;margin:0.8rem 0 0;">{kam} · Cobre</p>
  </div>
</div>
"""

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Split Payments | Reporte de Aperturas",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
.main-header {
    background: linear-gradient(135deg, #266D6C 0%, #1a4f4e 100%);
    color: white; padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;
}
.main-header h1 { color: white; margin: 0; font-size: 1.8rem; }
.main-header p  { color: #c8e6e5; margin: 0.3rem 0 0; font-size: 0.95rem; }
.kpi-card {
    background: white; border-radius: 12px; padding: 1.2rem 1.5rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-left: 5px solid #266D6C; margin-bottom: 0.5rem;
}
.kpi-value { font-size: 2rem; font-weight: 700; color: #266D6C; margin: 0; }
.kpi-label { font-size: 0.85rem; color: #666; margin: 0; }
.kpi-delta { font-size: 0.8rem; color: #27AE60; font-weight: 600; }
.seg-card  { border-radius: 12px; padding: 1.2rem; margin-bottom: 0.8rem; border: 1.5px solid; }
.alert-box { background: #FDECEB; border: 1.5px solid #C0392B; border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: 0.8rem; }
.company-row { background: white; border-radius: 8px; padding: 0.7rem 1rem; margin: 0.3rem 0; border: 1px solid #e0e0e0; display: flex; align-items: center; gap: 0.8rem; }
.section-title { font-size: 1.1rem; font-weight: 700; color: #266D6C; border-bottom: 2px solid #266D6C; padding-bottom: 0.4rem; margin-bottom: 1rem; }
.action-card { background: #E4F0EF; border-radius: 10px; padding: 1rem; border-left: 4px solid #266D6C; font-size: 0.9rem; }
.msg-box { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 1rem; font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; }
.confirm-box { background: #FEF9E7; border: 2px solid #F4D03F; border-radius: 10px; padding: 1.2rem; margin: 1rem 0; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def kpi_card(label: str, value: str, delta: str = "", border_color: str = BRAND["primary"]) -> None:
    delta_html = f'<p class="kpi-delta">{delta}</p>' if delta else ""
    st.markdown(
        f'<div class="kpi-card" style="border-left-color:{border_color};">'
        f'<p class="kpi-value">{value}</p><p class="kpi-label">{label}</p>{delta_html}</div>',
        unsafe_allow_html=True,
    )

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()

def _pct_color(val: float, vmin: float = 0, vmax: float = 100,
               low: tuple = (255, 255, 255), high: tuple = (38, 109, 108)) -> str:
    """Devuelve CSS de color interpolado entre low y high según el valor (sin matplotlib)."""
    try:
        ratio = max(0.0, min(1.0, (float(val) - vmin) / max(vmax - vmin, 1)))
        r = int(low[0] + ratio * (high[0] - low[0]))
        g = int(low[1] + ratio * (high[1] - low[1]))
        b = int(low[2] + ratio * (high[2] - low[2]))
        text = "white" if ratio > 0.55 else "#212121"
        return f"background-color: rgb({r},{g},{b}); color: {text};"
    except Exception:
        return ""

def _open_color(val):
    return _pct_color(val, 0, 100, (255,255,255), (38,109,108))   # blanco → teal

def _click_color(val):
    return _pct_color(val, 0, 10, (255,255,255), (66,133,244))    # blanco → azul

def render_message(empresa: str, nombre: str, kam: str) -> dict:
    return {
        "subject": MSG_SUBJECT.format(empresa=empresa, nombre=nombre, kam=kam),
        "body":    MSG_BODY.format(empresa=empresa, nombre=nombre, kam=kam),
        "preview": MSG_HTML_PREVIEW.format(empresa=empresa, nombre=nombre, kam=kam),
    }


# ── Carga de datos ────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Cargando datos desde HubSpot...")
def get_data():
    df_contacts = load_campaign_data()
    df_accounts = aggregate_to_accounts(df_contacts)
    df_kam      = get_kam_summary(df_contacts)
    return df_contacts, df_accounts, df_kam


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        f'<div style="background:{BRAND["primary"]};padding:1rem;border-radius:10px;margin-bottom:1rem;">'
        f'<h3 style="color:white;margin:0;">📧 Split Payments</h3>'
        f'<p style="color:#c8e6e5;margin:0;font-size:0.8rem;">Reporte de Aperturas · Cobre</p></div>',
        unsafe_allow_html=True,
    )
    if st.button("🔄 Actualizar datos de HubSpot", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("**Filtros globales**")

    df_contacts_raw, df_accounts_raw, df_kam_raw = get_data()

    kams_available = sorted(df_contacts_raw["kam"].unique().tolist())
    selected_kams  = st.multiselect("KAMs", kams_available, default=kams_available)
    selected_segs  = st.multiselect(
        "Segmentos", list(SEGMENTS.keys()), default=list(SEGMENTS.keys()),
        format_func=lambda s: f"{SEGMENTS[s]['emoji']} {s} — {SEGMENTS[s]['label']}",
    )
    company_search = st.text_input("Buscar empresa", placeholder="Ej: Bancolombia")

    st.markdown("---")
    st.markdown(
        f'<p style="font-size:0.75rem;color:#888;">{len(df_contacts_raw)} contactos · '
        f'{df_accounts_raw["company_name"].nunique()} empresas · {len(kams_available)} KAMs</p>',
        unsafe_allow_html=True,
    )

# ── Filtros ───────────────────────────────────────────────────────────────────

df_contacts = df_contacts_raw[df_contacts_raw["kam"].isin(selected_kams)].copy()
df_accounts = df_accounts_raw[
    df_accounts_raw["kam"].isin(selected_kams) &
    df_accounts_raw["segment"].isin(selected_segs)
].copy()
if company_search:
    df_accounts = df_accounts[df_accounts["company_name"].str.contains(company_search, case=False, na=False)]
df_kam      = df_kam_raw[df_kam_raw["KAM"].isin(selected_kams)].copy()
seg_counts  = get_segment_counts(df_accounts)

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown(
    '<div class="main-header">'
    '<h1>📧 Split Payments — Reporte de Aperturas</h1>'
    '<p>Campaña: PMM_Split Payments · "¿Cómo pagar $50.000.000 por Bre-B?" · Cobre</p>'
    '</div>',
    unsafe_allow_html=True,
)

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 Resumen General",
    "👤 Métricas por KAM",
    "🏢 Engagement por Empresa",
    "🎯 Segmentos",
    "✉️ Mensajes P2 & P3",
    "🚨 Alertas & Depuración",
    "💡 Conclusiones",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — RESUMEN GENERAL
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    total_contacts  = len(df_contacts)
    total_companies = df_accounts["company_name"].nunique()
    open_rate       = df_contacts["opened"].mean() * 100 if total_contacts else 0
    click_rate      = df_contacts["clicked"].mean() * 100 if total_contacts else 0
    interested      = seg_counts.get("P1",0) + seg_counts.get("P2",0) + seg_counts.get("P3",0)
    total_rereads   = int(df_contacts["open_count"].sum()) if "open_count" in df_contacts.columns else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: kpi_card("Contactos enviados", str(total_contacts))
    with c2: kpi_card("Empresas alcanzadas", str(total_companies))
    with c3: kpi_card("Tasa de apertura", f"{open_rate:.1f}%", border_color="#27AE60")
    with c4: kpi_card("Tasa de clic", f"{click_rate:.1f}%", border_color=BRAND["accent"])
    with c5: kpi_card("Empresas con interés", str(interested),
                      delta=f"{interested/total_companies*100:.0f}% del total" if total_companies else "",
                      border_color="#27AE60")
    with c6: kpi_card("Total re-lecturas", str(total_rereads),
                      delta="proxy de interés adicional", border_color=BRAND["primary"])

    st.markdown("<br>", unsafe_allow_html=True)

    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.markdown('<p class="section-title">Apertura y clic por KAM</p>', unsafe_allow_html=True)
        if not df_kam.empty:
            fig = go.Figure()
            fig.add_bar(x=df_kam["KAM"], y=df_kam["% Apertura"], name="% Apertura",
                        marker_color=BRAND["primary"],
                        text=df_kam["% Apertura"].apply(lambda x: f"{x:.0f}%"), textposition="outside")
            fig.add_bar(x=df_kam["KAM"], y=df_kam["% Clic"], name="% Clic",
                        marker_color=BRAND["accent"],
                        text=df_kam["% Clic"].apply(lambda x: f"{x:.0f}%"), textposition="outside")
            fig.update_layout(barmode="group", template="plotly_white",
                              plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                              margin=dict(t=10,b=10,l=0,r=0), height=320,
                              yaxis=dict(ticksuffix="%", range=[0,115]),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.markdown('<p class="section-title">Distribución P1–P5 (empresas)</p>', unsafe_allow_html=True)
        counts_data = [(p, seg_counts[p]) for p in SEGMENTS if seg_counts[p] > 0]
        if counts_data:
            labels = [f"{SEGMENTS[p]['emoji']} {p} · {SEGMENTS[p]['label']}" for p,_ in counts_data]
            values = [v for _,v in counts_data]
            colors = [SEGMENTS[p]["color"] for p,_ in counts_data]
            fig_pie = go.Figure(go.Pie(
                labels=labels, values=values, marker_colors=colors, hole=0.5,
                textinfo="label+percent",
                hovertemplate="<b>%{label}</b><br>%{value} empresas<extra></extra>",
            ))
            fig_pie.update_layout(template="plotly_white", showlegend=False,
                                  plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                  margin=dict(t=10,b=10,l=0,r=0), height=320)
            st.plotly_chart(fig_pie, use_container_width=True)

    # Funnel
    st.markdown('<p class="section-title">Embudo de campaña</p>', unsafe_allow_html=True)
    fig_f = go.Figure(go.Funnel(
        y=["Enviados", "Abrieron", "Hicieron clic"],
        x=[total_contacts, int(df_contacts["opened"].sum()), int(df_contacts["clicked"].sum())],
        marker_color=[BRAND["primary"], BRAND["accent"], "#27AE60"],
        textinfo="value+percent initial",
    ))
    fig_f.update_layout(template="plotly_white", plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10,b=10,l=50,r=50), height=200)
    st.plotly_chart(fig_f, use_container_width=True)



# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MÉTRICAS POR KAM
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown('<p class="section-title">Resumen de envío por KAM</p>', unsafe_allow_html=True)

    if not df_kam.empty:
        seg_by_kam = (
            df_accounts.groupby(["kam","segment"]).size()
            .unstack(fill_value=0).reindex(columns=list(SEGMENTS.keys()), fill_value=0)
        )
        kam_full = df_kam.set_index("KAM").join(seg_by_kam, how="left").fillna(0).reset_index()
        for p in SEGMENTS:
            if p not in kam_full.columns: kam_full[p] = 0
            kam_full[p] = kam_full[p].astype(int)

        display_cols = ["KAM","Contactos","Abrieron","% Apertura","Clicaron","% Clic","Empresas"] + list(SEGMENTS.keys())
        st.dataframe(
            kam_full[display_cols].style
            .applymap(_open_color,  subset=["% Apertura"])
            .applymap(_click_color, subset=["% Clic"])
            .format({"% Apertura": "{:.1f}%", "% Clic": "{:.1f}%"}),
            use_container_width=True, hide_index=True,
        )

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown('<p class="section-title">Empresas alcanzadas</p>', unsafe_allow_html=True)
            fig = px.bar(df_kam.sort_values("Empresas"), x="Empresas", y="KAM",
                         orientation="h", color_discrete_sequence=[BRAND["primary"]],
                         text="Empresas", template="plotly_white")
            fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                              margin=dict(t=10,b=10,l=0,r=0), height=300, xaxis_title="", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            st.markdown('<p class="section-title">Hot Leads (P1) por KAM</p>', unsafe_allow_html=True)
            p1 = df_accounts[df_accounts["segment"]=="P1"].groupby("kam").size().reset_index(name="P1")
            if not p1.empty:
                fig2 = px.bar(p1.sort_values("P1"), x="P1", y="kam", orientation="h",
                              color_discrete_sequence=["#27AE60"], text="P1", template="plotly_white")
                fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                   margin=dict(t=10,b=10,l=0,r=0), height=300, xaxis_title="", yaxis_title="")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Sin P1 para los filtros actuales.")

        st.markdown('<p class="section-title">Heatmap de segmentos por KAM</p>', unsafe_allow_html=True)
        pivot = df_accounts.groupby(["kam","segment"]).size().unstack(fill_value=0).reindex(columns=list(SEGMENTS.keys()), fill_value=0)
        if not pivot.empty:
            fig_h = px.imshow(pivot, color_continuous_scale="Teal", aspect="auto", text_auto=True, template="plotly_white")
            fig_h.update_layout(margin=dict(t=10,b=10,l=0,r=0), height=300,
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_h, use_container_width=True)

    st.download_button("⬇️ Descargar métricas KAM (.xlsx)",
                       data=df_to_excel_bytes(df_kam),
                       file_name="split_payments_metricas_kam.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ENGAGEMENT POR EMPRESA
# ═══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown('<p class="section-title">Engagement por empresa</p>', unsafe_allow_html=True)

    col_s, col_o = st.columns([2,1])
    with col_s:
        sort_map = {"Segmento":"segment","% Apertura":"open_rate","% Clic":"click_rate","Contactos":"total_contacts","Empresa":"company_name"}
        sort_by  = st.selectbox("Ordenar por", list(sort_map.keys()))
    with col_o:
        asc = st.checkbox("Ascendente", value=False)

    df_d = df_accounts.sort_values(sort_map[sort_by], ascending=asc).copy()
    df_t = df_d[["company_name","kam","segment","total_contacts","opened_count","open_rate","clicked_count","click_rate","has_bounced"]].copy()
    df_t["open_rate"]  = (df_t["open_rate"]*100).round(1)
    df_t["click_rate"] = (df_t["click_rate"]*100).round(1)
    df_t.columns = ["Empresa","KAM","Segmento","Contactos","Abrieron","% Apertura","Clicaron","% Clic","Bounce?"]

    def _color_seg(v):
        cfg = SEGMENTS.get(v, {})
        return f"color:{cfg.get('color','#000')};background:{cfg.get('bg','#fff')};font-weight:bold;border-radius:4px;"

    st.dataframe(
        df_t.style.applymap(_color_seg, subset=["Segmento"])
        .applymap(_open_color,  subset=["% Apertura"])
        .applymap(_click_color, subset=["% Clic"])
        .format({"% Apertura":"{:.1f}%","% Clic":"{:.1f}%"}),
        use_container_width=True, hide_index=True, height=450,
    )

    st.markdown('<p class="section-title">Detalle de contactos por empresa</p>', unsafe_allow_html=True)
    det = st.text_input("Buscar empresa para ver contactos", placeholder="Escribe el nombre...", key="det")
    if det:
        matches = df_d[df_d["company_name"].str.contains(det, case=False, na=False)]
        if matches.empty:
            st.warning(f"No encontré '{det}'")
        for _, row in matches.iterrows():
            cfg = SEGMENTS[row["segment"]]
            with st.expander(f"{cfg['emoji']} **{row['company_name']}** — {row['kam']} | {row['segment']} | {row['opened_count']}/{row['total_contacts']} abrieron · {row['clicked_count']} clics", expanded=True):
                cdf = pd.DataFrame(row["contacts"])
                if not cdf.empty:
                    cdf["Abrió"] = cdf["opened"].map({True:"✅",False:"❌"})
                    cdf["Clic"]  = cdf["clicked"].map({True:"✅",False:"❌"})
                    if "open_count" in cdf.columns:
                        cdf["Re-lecturas"] = cdf["open_count"].apply(lambda x: f"👁 {x}x" if x > 1 else "")
                    show = [c for c in ["name","email","jobtitle","Abrió","Clic","Re-lecturas"] if c in cdf.columns]
                    st.dataframe(cdf[show].rename(columns={"name":"Nombre","email":"Email","jobtitle":"Cargo"}),
                                 use_container_width=True, hide_index=True)

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button("⬇️ Exportar empresas (.xlsx)", data=df_to_excel_bytes(df_t),
                           file_name="split_payments_empresas.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    with col_dl2:
        st.download_button("⬇️ Exportar (.csv)", data=df_t.to_csv(index=False).encode(),
                           file_name="split_payments_empresas.csv", mime="text/csv",
                           use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — SEGMENTOS (con confirmación antes de crear listas)
# ═══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown('<p class="section-title">Segmentos P1–P5</p>', unsafe_allow_html=True)

    cols_top = st.columns(3)
    cols_bot = st.columns(2)
    seg_cols = list(cols_top) + list(cols_bot)

    for idx, (seg, cfg) in enumerate(SEGMENTS.items()):
        count = seg_counts.get(seg, 0)
        df_seg = df_accounts[df_accounts["segment"] == seg]
        with seg_cols[idx]:
            st.markdown(
                f'<div class="seg-card" style="border-color:{cfg["color"]};background:{cfg["bg"]};">'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<span style="font-size:1.5rem;">{cfg["emoji"]}</span>'
                f'<span style="font-size:2rem;font-weight:700;color:{cfg["color"]};">{count}</span></div>'
                f'<p style="font-weight:700;color:{cfg["color"]};margin:0.3rem 0 0;">{seg} · {cfg["label"]}</p>'
                f'<p style="color:#555;font-size:0.82rem;margin:0.2rem 0;">{cfg["desc"]}</p>'
                f'<p style="font-size:0.8rem;font-style:italic;color:{cfg["color"]};margin:0.5rem 0 0;">➜ {cfg["action"]}</p>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if count > 0:
                with st.expander(f"Ver {count} empresa(s)"):
                    for _, row in df_seg.iterrows():
                        st.markdown(
                            f'<div class="company-row">'
                            f'<span style="font-weight:600;flex:2;">{row["company_name"]}</span>'
                            f'<span style="color:#888;font-size:0.82rem;flex:1;">{row["kam"]}</span>'
                            f'<span style="font-size:0.8rem;">👁 {row["opened_count"]}/{row["total_contacts"]}</span>'
                            f'{"&nbsp;&nbsp;🖱 " + str(row["clicked_count"]) if row["clicked_count"] else ""}'
                            f'</div>', unsafe_allow_html=True)

    # ── Crear listas en HubSpot — con confirmación ────────────────────────────
    st.markdown("---")
    st.markdown('<p class="section-title">Crear listas en HubSpot</p>', unsafe_allow_html=True)
    st.markdown(
        '<div class="action-card">Crea listas estáticas en HubSpot para P2 (push email) y P3 (re-envío). '
        'Revisa el resumen antes de confirmar.</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        segs_to_create = st.multiselect("Segmentos", ["P2","P3"], default=["P2","P3"])
    with col_sel2:
        kam_list_filter = st.selectbox("Scope",
                                        ["Todos (lista global)"] + sorted(df_accounts["kam"].unique().tolist()))

    kam_fv = None if kam_list_filter == "Todos (lista global)" else kam_list_filter

    # Resumen de lo que se va a crear
    if segs_to_create:
        df_preview = df_accounts.copy()
        if kam_fv:
            df_preview = df_preview[df_preview["kam"] == kam_fv]

        st.markdown("**Resumen de lo que se creará:**")
        preview_rows = []
        for seg in segs_to_create:
            df_seg = df_preview[df_preview["segment"] == seg]
            n_companies = len(df_seg)
            n_contacts  = sum(len(r["contact_ids"]) for _, r in df_seg.iterrows())
            list_name   = f"Split Payments | {seg}" + (f" | {kam_fv}" if kam_fv else "")
            preview_rows.append({"Lista": list_name, "Empresas": n_companies, "Contactos": n_contacts})

        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

        # Estado de confirmación
        if "confirm_lists" not in st.session_state:
            st.session_state.confirm_lists = False
        if "hs_list_results" not in st.session_state:
            st.session_state.hs_list_results = []

        if not st.session_state.confirm_lists:
            st.markdown(
                '<div class="confirm-box">⚠️ <b>Antes de continuar</b> — estas listas se crearán '
                'en HubSpot y estarán listas para envío. Revisa el resumen de arriba.</div>',
                unsafe_allow_html=True,
            )
            col_ok, col_cancel = st.columns(2)
            with col_ok:
                if st.button("✅ Confirmar y crear listas", type="primary", use_container_width=True):
                    st.session_state.confirm_lists = True
                    st.rerun()
            with col_cancel:
                if st.button("❌ Cancelar", use_container_width=True):
                    st.session_state.confirm_lists = False
        else:
            if not st.session_state.hs_list_results:
                with st.spinner("Creando listas en HubSpot..."):
                    results = create_all_segment_lists(df_accounts, segments=segs_to_create, kam_filter=kam_fv)
                    st.session_state.hs_list_results = results

            for res in st.session_state.hs_list_results:
                icon = "✅" if res["contacts_added"] > 0 else "⚠️"
                if res["url"]:
                    st.success(f"{icon} **{res['name']}** {res['status']} · {res['contacts_added']} contactos · [Ver en HubSpot]({res['url']})")
                else:
                    st.warning(f"⚠️ {res['name']} — sin contactos.")

            if st.button("🔁 Crear otra lista", use_container_width=True):
                st.session_state.confirm_lists = False
                st.session_state.hs_list_results = []
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — MENSAJES P2 & P3
# ═══════════════════════════════════════════════════════════════════════════════

with tab5:
    st.markdown('<p class="section-title">Generador de mensajes — P2 y P3</p>', unsafe_allow_html=True)
    st.markdown(
        '<div class="action-card">Un solo template para P2 y P3, siguiendo la estructura del email original. '
        'Personalizado por empresa, contacto y KAM. Descarga el listado completo listo para envío.</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # Filtro por KAM únicamente
    msg_kam_filter = st.selectbox(
        "Filtrar por KAM",
        ["Todos"] + sorted(df_accounts["kam"].unique().tolist()),
        key="msg_kam",
    )

    # P2 + P3 juntos
    df_msg = df_accounts[df_accounts["segment"].isin(["P2", "P3"])].copy()
    if msg_kam_filter != "Todos":
        df_msg = df_msg[df_msg["kam"] == msg_kam_filter]

    st.markdown("---")

    if df_msg.empty:
        st.info("No hay empresas P2 o P3 con los filtros seleccionados.")
    else:
        p2_n = len(df_msg[df_msg["segment"] == "P2"])
        p3_n = len(df_msg[df_msg["segment"] == "P3"])
        st.markdown(f"**{len(df_msg)} empresa(s) en total** — 💙 P2: {p2_n} · 🟡 P3: {p3_n}")
        st.markdown("<br>", unsafe_allow_html=True)

        # Vista previa del email (estructura visual)
        with st.expander("👁 Vista previa del template", expanded=True):
            col_prev, col_txt = st.columns([1, 1])
            with col_prev:
                st.markdown("**Diseño del email:**")
                sample_preview = MSG_HTML_PREVIEW.format(
                    nombre="Nombre Contacto", empresa="Empresa Ejemplo", kam="Tu Nombre"
                )
                st.markdown(sample_preview, unsafe_allow_html=True)
            with col_txt:
                st.markdown("**Asunto:**")
                st.code(MSG_SUBJECT.replace("{empresa}", "Empresa Ejemplo")
                                   .replace("{nombre}", "Nombre")
                                   .replace("{kam}", "KAM"), language=None)
                st.markdown("**Cuerpo (texto plano):**")
                st.code(MSG_BODY.replace("{empresa}", "Empresa Ejemplo")
                                .replace("{nombre}", "Nombre Contacto")
                                .replace("{kam}", "Tu Nombre"), language=None)

        st.markdown("---")
        st.markdown("**Mensajes por empresa:**")
        st.markdown("<br>", unsafe_allow_html=True)

        # Generar todos los mensajes
        export_rows = []
        for _, row in df_msg.iterrows():
            empresa  = row["company_name"]
            kam      = row["kam"]
            contacts = row["contacts"]
            seg      = row["segment"]

            # P2: primer contacto que abrió | P3: primer contacto que NO abrió
            main_contact = next(
                (c for c in contacts if (c.get("opened") if seg == "P2" else not c.get("opened"))),
                contacts[0] if contacts else {},
            )
            nombre = main_contact.get("name", "").strip() or main_contact.get("email", empresa)
            msg    = render_message(empresa=empresa, nombre=nombre, kam=kam)

            export_rows.append({
                "Segmento":     seg,
                "Empresa":      empresa,
                "KAM":          kam,
                "Destinatario": nombre,
                "Email":        main_contact.get("email", ""),
                "Asunto":       msg["subject"],
                "Cuerpo":       msg["body"],
            })

        # Mostrar primeros 5 con preview visual
        for row_data in export_rows[:5]:
            cfg = SEGMENTS[row_data["Segmento"]]
            with st.expander(
                f"{cfg['emoji']} **{row_data['Empresa']}** — {row_data['KAM']} · {row_data['Destinatario']}",
                expanded=False,
            ):
                col_a, col_b = st.columns([1, 1])
                with col_a:
                    preview_html = MSG_HTML_PREVIEW.format(
                        nombre=row_data["Destinatario"],
                        empresa=row_data["Empresa"],
                        kam=row_data["KAM"],
                    )
                    st.markdown(preview_html, unsafe_allow_html=True)
                with col_b:
                    st.markdown(f"**Asunto:** {row_data['Asunto']}")
                    st.markdown(
                        f'<div class="msg-box">{row_data["Cuerpo"]}</div>',
                        unsafe_allow_html=True,
                    )

        if len(export_rows) > 5:
            st.markdown(f"*… y {len(export_rows) - 5} empresa(s) más en el archivo exportado.*")

        st.markdown("<br>", unsafe_allow_html=True)
        export_df = pd.DataFrame(export_rows)

        col_ex1, col_ex2 = st.columns(2)
        with col_ex1:
            st.download_button(
                "⬇️ Descargar todos los mensajes (.xlsx)",
                data=df_to_excel_bytes(export_df),
                file_name="split_payments_mensajes_P2_P3.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", use_container_width=True,
            )
        with col_ex2:
            st.download_button(
                "⬇️ Descargar (.csv)",
                data=export_df.to_csv(index=False).encode(),
                file_name="split_payments_mensajes_P2_P3.csv",
                mime="text/csv", use_container_width=True,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — ALERTAS & DEPURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

with tab6:
    col_p4, col_p5 = st.columns(2)

    with col_p4:
        st.markdown('<p class="section-title" style="color:#C0392B;">❄️ P4 — Sin interacción</p>', unsafe_allow_html=True)
        df_p4 = df_accounts[df_accounts["segment"] == "P4"]
        if len(df_p4) == 0:
            st.success("Sin cuentas P4 con los filtros actuales.")
        else:
            st.markdown(
                f'<div class="alert-box"><b>⚠️ {len(df_p4)} empresa(s) sin interacción</b><br>'
                f'Acción: contacto directo por WhatsApp vía KAM.</div>', unsafe_allow_html=True)
            for _, row in df_p4.iterrows():
                emails_str = ", ".join([c.get("email","") for c in row["contacts"][:2]])
                st.markdown(
                    f'<div class="company-row"><div style="flex:1;">'
                    f'<b>{row["company_name"]}</b><br>'
                    f'<span style="color:#888;font-size:0.8rem;">KAM: {row["kam"]} · {row["total_contacts"]} contacto(s)</span><br>'
                    f'<span style="color:#aaa;font-size:0.75rem;">{emails_str}</span>'
                    f'</div></div>', unsafe_allow_html=True)
            st.download_button("⬇️ Exportar P4 para WhatsApp KAM",
                               data=df_to_excel_bytes(df_p4[["company_name","kam","total_contacts"]].rename(columns={"company_name":"Empresa","kam":"KAM","total_contacts":"Contactos"})),
                               file_name="split_payments_P4.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)

    with col_p5:
        st.markdown('<p class="section-title" style="color:#7F8C8D;">🚫 P5 & Bounces — Depuración</p>', unsafe_allow_html=True)
        df_p5            = df_accounts[df_accounts["segment"] == "P5"]
        df_partial_bounce = df_accounts[(df_accounts["has_bounced"]) & (df_accounts["segment"] != "P5")]
        bounced_contacts = [c for _, row in df_accounts[df_accounts["has_bounced"]].iterrows()
                            for c in row["contacts"] if c.get("bounced")]

        if len(df_p5) == 0 and not bounced_contacts:
            st.success("Sin bounces detectados.")
        else:
            if len(df_p5) > 0:
                st.warning(f"🚫 {len(df_p5)} empresa(s) con bounce total")
            if bounced_contacts:
                bd = pd.DataFrame([{"Empresa": next((r["company_name"] for _,r in df_accounts.iterrows() if any(x["email"]==c["email"] for x in r["contacts"])), ""), "Email": c.get("email",""), "Nombre": c.get("name","")} for c in bounced_contacts])
                st.dataframe(bd, use_container_width=True, hide_index=True)
                st.download_button("⬇️ Lista de depuración (.xlsx)",
                                   data=df_to_excel_bytes(bd),
                                   file_name="split_payments_bounces.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — PLAN DE ACCIÓN
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — CONCLUSIONES
# ═══════════════════════════════════════════════════════════════════════════════

with tab7:
    st.markdown('<p class="section-title">Conclusiones y próximos pasos</p>', unsafe_allow_html=True)

    total_contacts  = len(df_contacts)
    total_companies = len(df_accounts)
    open_rate       = df_contacts["opened"].mean()*100 if total_contacts else 0
    click_rate      = df_contacts["clicked"].mean()*100 if total_contacts else 0
    p1 = seg_counts.get("P1",0); p2 = seg_counts.get("P2",0)
    p3 = seg_counts.get("P3",0); p4 = seg_counts.get("P4",0); p5 = seg_counts.get("P5",0)

    rereads = int(df_contacts["open_count"].sum()) if "open_count" in df_contacts.columns else 0

    st.markdown("#### 📌 Resumen ejecutivo")
    st.markdown(f"""
La campaña **Split Payments** ("¿Cómo pagar $50.000.000 por Bre-B?") alcanzó **{total_contacts} contactos**
en **{total_companies} empresas**, distribuidos entre **{len(selected_kams)} KAMs**.

- **Open rate: {open_rate:.1f}%** — rango B2B esperado
- **Click rate: {click_rate:.1f}%** — patrón recurrente de CTA débil (consistente con campañas anteriores)
- **Pipeline activo (P1+P2): {p1+p2} empresas** ({(p1+p2)/total_companies*100:.0f}% del total)
- **Re-lecturas totales: {rereads}** — señal de interés adicional más allá de la apertura única
    """)

    st.markdown("---")
    st.markdown("#### 🔍 Hallazgos clave")

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown(f'<div class="seg-card" style="border-color:#27AE60;background:#E8F8EE;">'
                    f'<b style="color:#27AE60;">🔥 P1 — {p1} Hot Leads</b><br><br>'
                    f'Contactos que abrieron <b>y</b> clicaron. Señal directa de intención. '
                    f'Requieren acción esta semana por parte del KAM antes de que el interés se enfríe.'
                    f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="seg-card" style="border-color:#D4820A;background:#FEF3DC;">'
                    f'<b style="color:#D4820A;">🟡 P3 — {p3} Empresas con apertura parcial</b><br><br>'
                    f'Solo algunos contactos abrieron. Probablemente el correo llegó a la persona incorrecta. '
                    f'Re-envío a los contactos que <b>no</b> abrieron puede mover la aguja.'
                    f'</div>', unsafe_allow_html=True)

    with col_r:
        st.markdown(f'<div class="seg-card" style="border-color:#266D6C;background:#E4F0EF;">'
                    f'<b style="color:#266D6C;">💙 P2 — {p2} Warm Leads</b><br><br>'
                    f'Todos abrieron pero ninguno clicó. Igual que en Llaves Wallets (68.4% open, 0% clic). '
                    f'El problema es el CTA, no el interés. '
                    f'Probar CTA de baja fricción: "¿15 min esta semana?" con link directo.'
                    f'</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="seg-card" style="border-color:#C0392B;background:#FDECEB;">'
                    f'<b style="color:#C0392B;">❄️ P4 — {p4} Sin interacción</b><br><br>'
                    f'No hacer re-envío masivo. Contacto personalizado por WhatsApp vía KAM. '
                    f'Revisar si hay reincidentes de campañas anteriores (Nequi, QR Bre-B, Llaves).'
                    f'</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### ✅ Próximos pasos")
    steps = []
    if p1 > 0: steps.append(f"**Esta semana** — KAMs contactan {p1} empresa(s) P1. Preparar propuesta o demo.")
    if p2 > 0: steps.append(f"**Próximos 3 días** — Generar mensajes P2 (Tab ✉️) y subir lista a HubSpot (Tab 🎯). Cambiar CTA a invitación directa.")
    if p3 > 0: steps.append(f"**Próxima semana** — Re-envío a {p3} empresa(s) P3 con nuevo subject line (Tab ✉️).")
    if p4 > 0: steps.append(f"**Paralelo** — {p4} empresa(s) P4: WhatsApp personalizado por KAM. Exportar lista en Tab 🚨.")
    if p5 > 0: steps.append(f"**Limpieza** — {p5} empresa(s) con bounce. Actualizar emails antes de próxima campaña.")
    steps.append("**Aprendizaje transversal** — El CTA es el problema recurrente en todas las campañas Cobre. Próximo envío: test A/B de CTA (demo vs contacto directo KAM).")

    for i, s in enumerate(steps, 1):
        st.markdown(f"{i}. {s}")

    st.markdown("---")
    col_e1, col_e2 = st.columns(2)
    all_export = df_accounts[["company_name","kam","segment","total_contacts","opened_count","open_rate","clicked_count","click_rate"]].copy()
    all_export["open_rate"]  = (all_export["open_rate"]*100).round(1)
    all_export["click_rate"] = (all_export["click_rate"]*100).round(1)
    all_export["Acción"] = all_export["segment"].map({p: SEGMENTS[p]["action"] for p in SEGMENTS})
    all_export.columns = ["Empresa","KAM","Segmento","Contactos","Abrieron","% Apertura","Clicaron","% Clic","Acción recomendada"]
    with col_e1:
        st.download_button("⬇️ Reporte completo (.xlsx)", data=df_to_excel_bytes(all_export),
                           file_name="split_payments_reporte_completo.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", use_container_width=True)
    with col_e2:
        st.download_button("⬇️ Reporte completo (.csv)", data=all_export.to_csv(index=False).encode(),
                           file_name="split_payments_reporte_completo.csv", mime="text/csv",
                           use_container_width=True)
