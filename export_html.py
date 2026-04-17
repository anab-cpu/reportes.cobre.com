"""
Genera split_payments_reporte.html — archivo estático autocontenido.
Carga datos en vivo de HubSpot, construye todos los gráficos y tablas,
y escribe un HTML que se puede compartir sin correr ningún servidor.

Uso:
    cd ~/split-payments-report
    python export_html.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from data_loader import load_campaign_data
from segmentation import SEGMENTS, aggregate_to_accounts, get_kam_summary, get_segment_counts

# ── Config ─────────────────────────────────────────────────────────────────────

BRAND = {
    "primary": "#266D6C",
    "accent":  "#518A89",
    "dark":    "#212121",
    "bg":      "#F1F0EC",
    "light":   "#E4F0EF",
}

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

# ── Helpers ────────────────────────────────────────────────────────────────────

def fig_html(fig: go.Figure, div_id: str = "", height: int | None = None) -> str:
    """Convierte figura Plotly a div HTML (sin JS de Plotly — se carga una sola vez)."""
    if height:
        fig.update_layout(height=height)
    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        div_id=div_id or None,
        config={"responsive": True, "displayModeBar": False},
    )


def _pct_color(val: float, vmin: float = 0, vmax: float = 100,
               low=(255,255,255), high=(38,109,108)) -> str:
    try:
        ratio = max(0.0, min(1.0, (float(val) - vmin) / max(vmax - vmin, 1)))
        r = int(low[0] + ratio*(high[0]-low[0]))
        g = int(low[1] + ratio*(high[1]-low[1]))
        b = int(low[2] + ratio*(high[2]-low[2]))
        text = "white" if ratio > 0.55 else "#212121"
        return f"background:{BRAND['primary'] if ratio>0.55 else f'rgb({r},{g},{b})'};color:{text};"
    except Exception:
        return ""

def _open_bg(val):  return _pct_color(val, 0, 100, (255,255,255), (38,109,108))
def _click_bg(val): return _pct_color(val, 0, 10,  (255,255,255), (66,133,244))

def seg_style(seg: str) -> str:
    cfg = SEGMENTS.get(seg, {})
    return f"color:{cfg.get('color','#333')};background:{cfg.get('bg','#eee')};font-weight:700;border-radius:4px;padding:2px 6px;"

def esc(s: str) -> str:
    """Escapa HTML básico para contenido de tabla."""
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def kpi_card_html(label: str, value: str, delta: str = "", color: str = BRAND["primary"]) -> str:
    delta_html = f'<p class="kpi-delta">{esc(delta)}</p>' if delta else ""
    return (
        f'<div class="kpi-card" style="border-left-color:{color};">'
        f'<p class="kpi-value">{esc(value)}</p>'
        f'<p class="kpi-label">{esc(label)}</p>{delta_html}</div>'
    )


# ── Construcción de secciones ──────────────────────────────────────────────────

def build_tab1(df_contacts: pd.DataFrame, df_accounts: pd.DataFrame,
               df_kam: pd.DataFrame, seg_counts: dict) -> str:

    total_contacts  = len(df_contacts)
    total_companies = len(df_accounts)
    open_rate       = df_contacts["opened"].mean() * 100 if total_contacts else 0
    click_rate      = df_contacts["clicked"].mean() * 100 if total_contacts else 0
    interested      = seg_counts.get("P1",0) + seg_counts.get("P2",0) + seg_counts.get("P3",0)
    total_rereads   = int(df_contacts["open_count"].sum()) if "open_count" in df_contacts.columns else 0

    kpis = "".join([
        kpi_card_html("Contactos enviados",    str(total_contacts)),
        kpi_card_html("Empresas alcanzadas",   str(total_companies)),
        kpi_card_html("Tasa de apertura",      f"{open_rate:.1f}%",  color="#27AE60"),
        kpi_card_html("Tasa de clic",          f"{click_rate:.1f}%", color=BRAND["accent"]),
        kpi_card_html("Empresas con interés",  str(interested),
                      delta=f"{interested/total_companies*100:.0f}% del total" if total_companies else "",
                      color="#27AE60"),
        kpi_card_html("Total re-lecturas",     str(total_rereads),
                      delta="proxy de interés adicional", color=BRAND["primary"]),
    ])

    # Bar chart apertura/clic por KAM
    fig_bar = go.Figure()
    fig_bar.add_bar(x=df_kam["KAM"], y=df_kam["% Apertura"], name="% Apertura",
                    marker_color=BRAND["primary"],
                    text=df_kam["% Apertura"].apply(lambda x: f"{x:.0f}%"), textposition="outside")
    fig_bar.add_bar(x=df_kam["KAM"], y=df_kam["% Clic"], name="% Clic",
                    marker_color=BRAND["accent"],
                    text=df_kam["% Clic"].apply(lambda x: f"{x:.0f}%"), textposition="outside")
    fig_bar.update_layout(barmode="group", template="plotly_white",
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(t=10,b=10,l=0,r=0), height=320,
                          yaxis=dict(ticksuffix="%", range=[0,115]),
                          legend=dict(orientation="h", yanchor="bottom", y=1.02))

    # Donut P1-P5
    counts_data = [(p, seg_counts[p]) for p in SEGMENTS if seg_counts[p] > 0]
    fig_pie = go.Figure(go.Pie(
        labels=[f"{SEGMENTS[p]['emoji']} {p} · {SEGMENTS[p]['label']}" for p,_ in counts_data],
        values=[v for _,v in counts_data],
        marker_colors=[SEGMENTS[p]["color"] for p,_ in counts_data],
        hole=0.5, textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>%{value} empresas<extra></extra>",
    ))
    fig_pie.update_layout(template="plotly_white", showlegend=False,
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(t=10,b=10,l=0,r=0), height=320)

    # Funnel
    fig_f = go.Figure(go.Funnel(
        y=["Enviados", "Abrieron", "Hicieron clic"],
        x=[total_contacts, int(df_contacts["opened"].sum()), int(df_contacts["clicked"].sum())],
        marker_color=[BRAND["primary"], BRAND["accent"], "#27AE60"],
        textinfo="value+percent initial",
    ))
    fig_f.update_layout(template="plotly_white", plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)", margin=dict(t=10,b=10,l=50,r=50), height=220)

    return f"""
<div class="kpi-grid">{kpis}</div>

<div class="two-col" style="margin-top:1.5rem;">
  <div>
    <div class="section-title">Apertura y clic por KAM</div>
    {fig_html(fig_bar)}
  </div>
  <div>
    <div class="section-title">Distribución P1–P5 (empresas)</div>
    {fig_html(fig_pie)}
  </div>
</div>

<div style="margin-top:1.5rem;">
  <div class="section-title">Embudo de campaña</div>
  {fig_html(fig_f)}
</div>
"""


def build_tab2(df_contacts: pd.DataFrame, df_accounts: pd.DataFrame, df_kam: pd.DataFrame) -> str:

    seg_by_kam = (
        df_accounts.groupby(["kam","segment"]).size()
        .unstack(fill_value=0).reindex(columns=list(SEGMENTS.keys()), fill_value=0)
    )
    kam_full = df_kam.set_index("KAM").join(seg_by_kam, how="left").fillna(0).reset_index()
    for p in SEGMENTS:
        if p not in kam_full.columns:
            kam_full[p] = 0
        kam_full[p] = kam_full[p].astype(int)

    # Table header
    seg_headers = "".join(f"<th>{p}</th>" for p in SEGMENTS)
    header = f"<tr><th>KAM</th><th>Contactos</th><th>Abrieron</th><th>% Apertura</th><th>Clicaron</th><th>% Clic</th><th>Empresas</th>{seg_headers}</tr>"

    rows_html = ""
    for _, r in kam_full.iterrows():
        open_style  = _open_bg(r["% Apertura"])
        click_style = _click_bg(r["% Clic"])
        seg_cells = "".join(f'<td>{int(r.get(p,0))}</td>' for p in SEGMENTS)
        rows_html += (
            f'<tr><td><b>{esc(r["KAM"])}</b></td>'
            f'<td>{int(r["Contactos"])}</td>'
            f'<td>{int(r["Abrieron"])}</td>'
            f'<td style="{open_style}">{r["% Apertura"]:.1f}%</td>'
            f'<td>{int(r["Clicaron"])}</td>'
            f'<td style="{click_style}">{r["% Clic"]:.1f}%</td>'
            f'<td>{int(r["Empresas"])}</td>'
            f'{seg_cells}</tr>'
        )

    # Bar charts
    fig_emp = px.bar(df_kam.sort_values("Empresas"), x="Empresas", y="KAM",
                     orientation="h", color_discrete_sequence=[BRAND["primary"]],
                     text="Empresas", template="plotly_white")
    fig_emp.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(t=10,b=10,l=0,r=0), height=320, xaxis_title="", yaxis_title="")

    p1_data = df_accounts[df_accounts["segment"]=="P1"].groupby("kam").size().reset_index(name="P1")
    if not p1_data.empty:
        fig_p1 = px.bar(p1_data.sort_values("P1"), x="P1", y="kam", orientation="h",
                        color_discrete_sequence=["#27AE60"], text="P1", template="plotly_white")
        fig_p1.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                             margin=dict(t=10,b=10,l=0,r=0), height=320, xaxis_title="", yaxis_title="")
        p1_html = fig_html(fig_p1)
    else:
        p1_html = '<p style="color:#888;padding:1rem;">Sin Hot Leads (P1).</p>'

    # Heatmap
    pivot = df_accounts.groupby(["kam","segment"]).size().unstack(fill_value=0).reindex(columns=list(SEGMENTS.keys()), fill_value=0)
    fig_h = px.imshow(pivot, color_continuous_scale="Teal", aspect="auto", text_auto=True, template="plotly_white")
    fig_h.update_layout(margin=dict(t=10,b=10,l=0,r=0), height=320,
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")

    return f"""
<div class="section-title">Resumen de envío por KAM</div>
<div class="table-wrap">
  <table class="data-table">
    <thead>{header}</thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>

<div class="two-col" style="margin-top:1.5rem;">
  <div>
    <div class="section-title">Empresas alcanzadas</div>
    {fig_html(fig_emp)}
  </div>
  <div>
    <div class="section-title">Hot Leads (P1) por KAM</div>
    {p1_html}
  </div>
</div>

<div style="margin-top:1.5rem;">
  <div class="section-title">Heatmap de segmentos por KAM</div>
  {fig_html(fig_h)}
</div>
"""


def build_tab3(df_accounts: pd.DataFrame) -> str:
    df_d = df_accounts.copy()
    df_d["open_pct"]  = (df_d["open_rate"]  * 100).round(1)
    df_d["click_pct"] = (df_d["click_rate"] * 100).round(1)

    header = "<tr><th>Empresa</th><th>KAM</th><th>Segmento</th><th>Contactos</th><th>Abrieron</th><th>% Apertura</th><th>Clicaron</th><th>% Clic</th><th>Bounce?</th></tr>"
    rows_html = ""
    for _, r in df_d.iterrows():
        open_style  = _open_bg(r["open_pct"])
        click_style = _click_bg(r["click_pct"])
        bounce_icon = "⚠️" if r["has_bounced"] else ""
        rows_html += (
            f'<tr>'
            f'<td><b>{esc(r["company_name"])}</b></td>'
            f'<td>{esc(r["kam"])}</td>'
            f'<td><span style="{seg_style(r["segment"])}">{r["segment"]}</span></td>'
            f'<td>{r["total_contacts"]}</td>'
            f'<td>{r["opened_count"]}</td>'
            f'<td style="{open_style}">{r["open_pct"]:.1f}%</td>'
            f'<td>{r["clicked_count"]}</td>'
            f'<td style="{click_style}">{r["click_pct"]:.1f}%</td>'
            f'<td style="text-align:center;">{bounce_icon}</td>'
            f'</tr>'
        )

    # Detalle de contactos por empresa (accordions)
    details_html = ""
    for _, row in df_d.iterrows():
        cdf = pd.DataFrame(row["contacts"])
        if cdf.empty:
            continue
        contact_rows = ""
        for _, c in cdf.iterrows():
            abrio = "✅" if c.get("opened") else "❌"
            clic  = "✅" if c.get("clicked") else "❌"
            rereads = f"👁 {c.get('open_count',0)}x" if c.get("open_count",0) > 1 else ""
            contact_rows += (
                f'<tr>'
                f'<td>{esc(c.get("name",""))}</td>'
                f'<td>{esc(c.get("email",""))}</td>'
                f'<td>{esc(c.get("jobtitle",""))}</td>'
                f'<td style="text-align:center;">{abrio}</td>'
                f'<td style="text-align:center;">{clic}</td>'
                f'<td style="text-align:center;">{rereads}</td>'
                f'</tr>'
            )
        cfg = SEGMENTS[row["segment"]]
        details_html += f"""
<details class="company-detail">
  <summary style="color:{cfg["color"]};">{cfg["emoji"]} <b>{esc(row["company_name"])}</b> — {esc(row["kam"])} | {row["segment"]} | {row["opened_count"]}/{row["total_contacts"]} abrieron · {row["clicked_count"]} clics</summary>
  <div style="padding:0.8rem 1rem 0;">
    <table class="data-table contact-table">
      <thead><tr><th>Nombre</th><th>Email</th><th>Cargo</th><th>Abrió</th><th>Clic</th><th>Re-lecturas</th></tr></thead>
      <tbody>{contact_rows}</tbody>
    </table>
  </div>
</details>
"""

    return f"""
<div class="section-title">Engagement por empresa</div>
<div class="table-wrap">
  <table class="data-table sortable" id="tab3-table">
    <thead>{header}</thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>

<div class="section-title" style="margin-top:2rem;">Detalle de contactos por empresa</div>
{details_html}
"""


def build_tab4(df_accounts: pd.DataFrame, seg_counts: dict) -> str:
    seg_cols_html = ""
    for seg, cfg in SEGMENTS.items():
        count = seg_counts.get(seg, 0)
        df_seg = df_accounts[df_accounts["segment"] == seg]

        company_items = ""
        for _, row in df_seg.iterrows():
            click_badge = f"&nbsp;&nbsp;🖱 {row['clicked_count']}" if row["clicked_count"] else ""
            company_items += (
                f'<div class="company-row">'
                f'<span style="font-weight:600;flex:2;">{esc(row["company_name"])}</span>'
                f'<span style="color:#888;font-size:0.82rem;flex:1;">{esc(row["kam"])}</span>'
                f'<span style="font-size:0.8rem;">👁 {row["opened_count"]}/{row["total_contacts"]}{click_badge}</span>'
                f'</div>'
            )

        companies_section = ""
        if count > 0:
            companies_section = f'<details><summary style="font-size:0.85rem;cursor:pointer;color:{cfg["color"]};">Ver {count} empresa(s)</summary><div style="margin-top:0.5rem;">{company_items}</div></details>'

        seg_cols_html += f"""
<div class="seg-card" style="border-color:{cfg["color"]};background:{cfg["bg"]};">
  <div style="display:flex;justify-content:space-between;">
    <span style="font-size:1.5rem;">{cfg["emoji"]}</span>
    <span style="font-size:2rem;font-weight:700;color:{cfg["color"]};">{count}</span>
  </div>
  <p style="font-weight:700;color:{cfg["color"]};margin:0.3rem 0 0;">{seg} · {cfg["label"]}</p>
  <p style="color:#555;font-size:0.82rem;margin:0.2rem 0;">{cfg["desc"]}</p>
  <p style="font-size:0.8rem;font-style:italic;color:{cfg["color"]};margin:0.5rem 0;">➜ {cfg["action"]}</p>
  {companies_section}
</div>
"""

    return f"""
<div class="section-title">Segmentos P1–P5</div>
<div class="seg-grid">{seg_cols_html}</div>
"""


def build_tab5(df_accounts: pd.DataFrame) -> str:
    df_msg = df_accounts[df_accounts["segment"].isin(["P2","P3"])].copy()
    if df_msg.empty:
        return '<p style="color:#888;padding:1rem;">Sin empresas P2 o P3.</p>'

    p2_n = len(df_msg[df_msg["segment"]=="P2"])
    p3_n = len(df_msg[df_msg["segment"]=="P3"])

    # Template preview
    sample_subject = MSG_SUBJECT.format(empresa="Empresa Ejemplo", nombre="Nombre", kam="KAM")
    sample_body    = MSG_BODY.format(empresa="Empresa Ejemplo", nombre="Nombre Contacto", kam="Tu Nombre")
    template_preview = f"""
<div class="template-preview">
  <div class="msg-preview-card">
    <div style="background:#f8f7f3;padding:1rem;text-align:center;border-bottom:1px solid #e0e0e0;">
      <span style="font-weight:700;font-size:1rem;letter-spacing:1px;">⋮⋮ Cobre</span>
    </div>
    <div style="padding:1.2rem 1.5rem;">
      <h3 style="font-size:1.2rem;font-weight:700;margin:0 0 0.6rem;">El monto de tus pagos ya no determina su velocidad.</h3>
      <p style="color:#555;font-size:0.88rem;margin:0 0 1rem;">Ahora puedes enviar pagos que superen el tope de Bre-B y que sigan viajando por el riel más rápido.</p>
    </div>
    <div style="background:#1a1a1a;color:white;padding:1.2rem 1.5rem;">
      <p style="font-size:0.82rem;margin:0 0 0.8rem;line-height:1.6;">Hola <b>Nombre Contacto</b>,<br><br>
      Te escribo para retomar el correo que te envié hace unos días sobre Split Payments.<br><br>
      Con Split Payments puedes dividir automáticamente cualquier transferencia que exceda el límite de monto del riel...</p>
      <p style="font-size:0.82rem;font-weight:700;margin:0.8rem 0 0.4rem;">Así funciona:</p>
      <p style="font-size:0.82rem;margin:0 0 0.3rem;">→ Tú envías un solo pago. Cobre lo divide y procesa en tiempo real.</p>
      <p style="font-size:0.82rem;margin:0;">→ Un pago de 50M COP → 5 transacciones por Bre-B automáticamente.</p>
    </div>
    <div style="padding:1rem 1.5rem;text-align:center;border-top:1px solid #e0e0e0;">
      <div style="display:inline-block;background:#266D6C;color:white;padding:0.6rem 1.3rem;border-radius:6px;font-size:0.85rem;font-weight:600;">Actívalo con tu Gerente de Cuenta →</div>
      <p style="color:#888;font-size:0.78rem;margin:0.6rem 0 0;">Tu Nombre · Cobre</p>
    </div>
  </div>
  <div style="flex:1;min-width:0;">
    <p style="font-weight:700;margin-bottom:0.3rem;">Asunto:</p>
    <div class="code-block">{esc(sample_subject)}</div>
    <p style="font-weight:700;margin:1rem 0 0.3rem;">Cuerpo (texto plano):</p>
    <div class="code-block" style="font-size:0.8rem;">{esc(sample_body)}</div>
  </div>
</div>
"""

    # Messages table
    msg_rows = []
    for _, row in df_msg.iterrows():
        empresa  = row["company_name"]
        kam      = row["kam"]
        contacts = row["contacts"]
        seg      = row["segment"]
        main_contact = next(
            (c for c in contacts if (c.get("opened") if seg=="P2" else not c.get("opened"))),
            contacts[0] if contacts else {},
        )
        nombre = main_contact.get("name","").strip() or main_contact.get("email", empresa)
        cfg = SEGMENTS[seg]

        subj = MSG_SUBJECT.format(empresa=empresa, nombre=nombre, kam=kam)
        body = MSG_BODY.format(empresa=empresa, nombre=nombre, kam=kam)

        msg_rows.append({
            "seg": seg, "cfg": cfg,
            "empresa": empresa, "kam": kam,
            "nombre": nombre, "email": main_contact.get("email",""),
            "subject": subj, "body": body,
        })

    accordions = ""
    for m in msg_rows:
        accordions += f"""
<details class="company-detail">
  <summary style="color:{m["cfg"]["color"]};">{m["cfg"]["emoji"]} <b>{esc(m["empresa"])}</b> — {esc(m["kam"])} · {esc(m["nombre"])}</summary>
  <div style="padding:0.8rem 1rem;display:flex;gap:1.5rem;flex-wrap:wrap;">
    <div style="flex:1;min-width:220px;">
      <p style="margin:0 0 0.3rem;font-weight:700;">Para: {esc(m["nombre"])} &lt;{esc(m["email"])}&gt;</p>
      <p style="margin:0 0 0.3rem;"><b>Asunto:</b> {esc(m["subject"])}</p>
      <div class="code-block" style="font-size:0.78rem;">{esc(m["body"])}</div>
    </div>
  </div>
</details>
"""

    return f"""
<div class="section-title">Generador de mensajes — P2 y P3</div>
<div class="action-card">Un solo template para P2 y P3, siguiendo la estructura del email original. Personalizado por empresa, contacto y KAM.</div>

<p style="margin:1rem 0;"><b>{len(df_msg)} empresa(s) en total</b> — 💙 P2: {p2_n} · 🟡 P3: {p3_n}</p>

<div class="section-title" style="margin-top:1rem;">Vista previa del template</div>
{template_preview}

<div class="section-title" style="margin-top:1.5rem;">Mensajes por empresa</div>
{accordions}
"""


def build_tab6(df_accounts: pd.DataFrame) -> str:
    df_p4 = df_accounts[df_accounts["segment"] == "P4"]
    df_p5 = df_accounts[df_accounts["segment"] == "P5"]
    bounced_contacts = [c for _, row in df_accounts[df_accounts["has_bounced"]].iterrows()
                        for c in row["contacts"] if c.get("bounced")]

    # P4
    if len(df_p4) == 0:
        p4_html = '<div class="success-box">Sin cuentas P4.</div>'
    else:
        items = "".join(
            f'<div class="company-row">'
            f'<div style="flex:1;">'
            f'<b>{esc(row["company_name"])}</b><br>'
            f'<span style="color:#888;font-size:0.8rem;">KAM: {esc(row["kam"])} · {row["total_contacts"]} contacto(s)</span><br>'
            f'<span style="color:#aaa;font-size:0.75rem;">{", ".join(c.get("email","") for c in row["contacts"][:2])}</span>'
            f'</div></div>'
            for _, row in df_p4.iterrows()
        )
        p4_html = f'<div class="alert-box">⚠️ <b>{len(df_p4)} empresa(s) sin interacción</b><br>Acción: contacto directo por WhatsApp vía KAM.</div>{items}'

    # P5 / bounces
    if len(df_p5) == 0 and not bounced_contacts:
        p5_html = '<div class="success-box">Sin bounces detectados.</div>'
    else:
        bounce_rows = "".join(
            f'<tr><td>{esc(c.get("name",""))}</td><td>{esc(c.get("email",""))}</td></tr>'
            for c in bounced_contacts
        )
        p5_html = ""
        if len(df_p5) > 0:
            p5_html += f'<div class="alert-box" style="border-color:#7F8C8D;background:#F2F3F4;">🚫 <b>{len(df_p5)} empresa(s) con bounce total</b></div>'
        if bounce_rows:
            p5_html += f'<div class="table-wrap"><table class="data-table"><thead><tr><th>Nombre</th><th>Email</th></tr></thead><tbody>{bounce_rows}</tbody></table></div>'

    return f"""
<div class="two-col">
  <div>
    <div class="section-title" style="color:#C0392B;">❄️ P4 — Sin interacción</div>
    {p4_html}
  </div>
  <div>
    <div class="section-title" style="color:#7F8C8D;">🚫 P5 & Bounces — Depuración</div>
    {p5_html}
  </div>
</div>
"""


def build_tab7(df_contacts: pd.DataFrame, df_accounts: pd.DataFrame, seg_counts: dict) -> str:
    total_contacts  = len(df_contacts)
    total_companies = len(df_accounts)
    open_rate       = df_contacts["opened"].mean()*100 if total_contacts else 0
    click_rate      = df_contacts["clicked"].mean()*100 if total_contacts else 0
    p1 = seg_counts.get("P1",0); p2 = seg_counts.get("P2",0)
    p3 = seg_counts.get("P3",0); p4 = seg_counts.get("P4",0); p5 = seg_counts.get("P5",0)
    rereads = int(df_contacts["open_count"].sum()) if "open_count" in df_contacts.columns else 0

    steps = []
    if p1 > 0: steps.append(f"<b>Esta semana</b> — KAMs contactan {p1} empresa(s) P1. Preparar propuesta o demo.")
    if p2 > 0: steps.append(f"<b>Próximos 3 días</b> — Enviar mensajes P2 (ver Tab ✉️). Cambiar CTA a invitación directa.")
    if p3 > 0: steps.append(f"<b>Próxima semana</b> — Re-envío a {p3} empresa(s) P3 con nuevo subject line.")
    if p4 > 0: steps.append(f"<b>Paralelo</b> — {p4} empresa(s) P4: WhatsApp personalizado por KAM.")
    if p5 > 0: steps.append(f"<b>Limpieza</b> — {p5} empresa(s) con bounce. Actualizar emails antes de próxima campaña.")
    steps.append("<b>Aprendizaje transversal</b> — El CTA es el problema recurrente. Próximo envío: test A/B de CTA (demo vs contacto directo KAM).")

    steps_html = "".join(f'<li>{s}</li>' for s in steps)

    cards = f"""
<div class="two-col">
  <div>
    <div class="seg-card" style="border-color:#27AE60;background:#E8F8EE;">
      <b style="color:#27AE60;">🔥 P1 — {p1} Hot Leads</b><br><br>
      Contactos que abrieron <b>y</b> clicaron. Señal directa de intención. Requieren acción esta semana por parte del KAM.
    </div>
    <div class="seg-card" style="border-color:#D4820A;background:#FEF3DC;margin-top:1rem;">
      <b style="color:#D4820A;">🟡 P3 — {p3} Empresas con apertura parcial</b><br><br>
      Solo algunos contactos abrieron. Re-envío a los que <b>no</b> abrieron puede mover la aguja.
    </div>
  </div>
  <div>
    <div class="seg-card" style="border-color:#266D6C;background:#E4F0EF;">
      <b style="color:#266D6C;">💙 P2 — {p2} Warm Leads</b><br><br>
      Todos abrieron pero ninguno clicó. El problema es el CTA, no el interés.
      Probar CTA de baja fricción: "¿15 min esta semana?" con link directo.
    </div>
    <div class="seg-card" style="border-color:#C0392B;background:#FDECEB;margin-top:1rem;">
      <b style="color:#C0392B;">❄️ P4 — {p4} Sin interacción</b><br><br>
      No hacer re-envío masivo. Contacto personalizado por WhatsApp vía KAM.
    </div>
  </div>
</div>
"""

    return f"""
<div class="section-title">Resumen ejecutivo</div>
<p>La campaña <b>Split Payments</b> ("¿Cómo pagar $50.000.000 por Bre-B?") alcanzó
<b>{total_contacts} contactos</b> en <b>{total_companies} empresas</b>.</p>
<ul>
  <li><b>Open rate: {open_rate:.1f}%</b> — rango B2B esperado</li>
  <li><b>Click rate: {click_rate:.1f}%</b> — patrón recurrente de CTA débil</li>
  <li><b>Pipeline activo (P1+P2): {p1+p2} empresas</b> ({(p1+p2)/total_companies*100:.0f}% del total)</li>
  <li><b>Re-lecturas totales: {rereads}</b> — señal de interés adicional</li>
</ul>

<hr style="margin:1.5rem 0;border:none;border-top:1px solid #ddd;">
<div class="section-title">Hallazgos clave</div>
{cards}

<hr style="margin:1.5rem 0;border:none;border-top:1px solid #ddd;">
<div class="section-title">Próximos pasos</div>
<ol style="padding-left:1.4rem;line-height:2;">{steps_html}</ol>
"""


# ── CSS global ─────────────────────────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #F1F0EC;
  color: #212121;
  font-size: 15px;
}
.page { max-width: 1280px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }

/* Header */
.main-header {
  background: linear-gradient(135deg, #266D6C 0%, #1a4f4e 100%);
  color: white; padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;
}
.main-header h1 { margin: 0; font-size: 1.7rem; }
.main-header p  { margin: 0.3rem 0 0; font-size: 0.9rem; color: #c8e6e5; }

/* KPI grid */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 0.8rem; }
.kpi-card {
  background: white; border-radius: 12px; padding: 1rem 1.2rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07); border-left: 5px solid #266D6C;
}
.kpi-value { font-size: 1.9rem; font-weight: 700; color: #266D6C; margin: 0; }
.kpi-label { font-size: 0.8rem; color: #666; margin: 0; }
.kpi-delta { font-size: 0.75rem; color: #27AE60; font-weight: 600; margin: 0.2rem 0 0; }

/* Tabs */
.tab-bar {
  display: flex; gap: 0; flex-wrap: wrap;
  background: white; border-radius: 12px 12px 0 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07); overflow: hidden;
  margin-bottom: 0;
}
.tab-btn {
  padding: 0.8rem 1.2rem; font-size: 0.88rem; font-weight: 600;
  color: #555; background: transparent; border: none; cursor: pointer;
  border-bottom: 3px solid transparent; white-space: nowrap;
  transition: color .2s, border-color .2s;
}
.tab-btn:hover   { color: #266D6C; background: #f5f5f5; }
.tab-btn.active  { color: #266D6C; border-bottom-color: #266D6C; background: #f9f9f9; }
.tab-content     { display: none; }
.tab-content.active { display: block; }
.tab-panel {
  background: white; border-radius: 0 0 12px 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  padding: 1.5rem; margin-bottom: 1.5rem;
}

/* Layouts */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
@media (max-width: 720px) { .two-col { grid-template-columns: 1fr; } }

/* Tables */
.table-wrap { overflow-x: auto; border-radius: 8px; }
.data-table {
  width: 100%; border-collapse: collapse; font-size: 0.85rem;
}
.data-table th {
  background: #266D6C; color: white;
  padding: 0.5rem 0.75rem; text-align: left; white-space: nowrap;
}
.data-table td { padding: 0.45rem 0.75rem; border-bottom: 1px solid #eee; }
.data-table tbody tr:hover { background: #f5fafa; }
.contact-table th { background: #518A89; }

/* Segment cards */
.seg-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
@media (max-width: 900px) { .seg-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 580px) { .seg-grid { grid-template-columns: 1fr; } }
.seg-card { border-radius: 12px; padding: 1.2rem; border: 1.5px solid; }

/* Company rows */
.company-row {
  display: flex; align-items: center; gap: 0.8rem;
  background: white; border-radius: 8px;
  padding: 0.6rem 0.9rem; margin: 0.3rem 0;
  border: 1px solid #e0e0e0;
}

/* Details/accordion */
.company-detail {
  background: #fafafa; border-radius: 8px;
  border: 1px solid #e8e8e8; margin: 0.4rem 0;
  overflow: hidden;
}
.company-detail summary {
  padding: 0.7rem 1rem; cursor: pointer;
  font-size: 0.9rem; list-style: none;
  user-select: none;
}
.company-detail summary::-webkit-details-marker { display: none; }
.company-detail summary::before { content: "▶ "; font-size: 0.7rem; color: #999; }
.company-detail[open] summary::before { content: "▼ "; }

/* Alert / success boxes */
.alert-box   { background: #FDECEB; border: 1.5px solid #C0392B; border-radius: 10px; padding: 0.9rem 1.1rem; margin-bottom: 0.8rem; }
.success-box { background: #E8F8EE; border: 1.5px solid #27AE60; border-radius: 10px; padding: 0.9rem 1.1rem; }
.action-card { background: #E4F0EF; border-radius: 10px; padding: 1rem; border-left: 4px solid #266D6C; font-size: 0.9rem; margin-bottom: 1rem; }

/* Section title */
.section-title {
  font-size: 1rem; font-weight: 700; color: #266D6C;
  border-bottom: 2px solid #266D6C;
  padding-bottom: 0.35rem; margin-bottom: 0.9rem;
}

/* Message template */
.template-preview { display: flex; gap: 2rem; flex-wrap: wrap; align-items: flex-start; }
.msg-preview-card {
  max-width: 440px; border: 1px solid #e0e0e0;
  border-radius: 12px; overflow: hidden; flex-shrink: 0;
}
.code-block {
  background: #f5f5f5; border: 1px solid #ddd;
  border-radius: 6px; padding: 0.8rem;
  font-family: monospace; font-size: 0.82rem;
  white-space: pre-wrap; word-break: break-word;
}

/* Footer */
.footer { text-align: center; color: #aaa; font-size: 0.78rem; margin-top: 2rem; }
"""


# ── Plantilla HTML principal ────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Split Payments — Reporte de Aperturas</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js" charset="utf-8"></script>
  <style>{css}</style>
</head>
<body>
<div class="page">

  <div class="main-header">
    <h1>📧 Split Payments — Reporte de Aperturas</h1>
    <p>Campaña: PMM_Split Payments · "¿Cómo pagar $50.000.000 por Bre-B?" · Cobre · Generado: {fecha}</p>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="showTab('tab1',this)">📊 Resumen</button>
    <button class="tab-btn" onclick="showTab('tab2',this)">👤 Por KAM</button>
    <button class="tab-btn" onclick="showTab('tab3',this)">🏢 Por Empresa</button>
    <button class="tab-btn" onclick="showTab('tab4',this)">🎯 Segmentos</button>
    <button class="tab-btn" onclick="showTab('tab5',this)">✉️ Mensajes P2 & P3</button>
    <button class="tab-btn" onclick="showTab('tab6',this)">🚨 Alertas</button>
    <button class="tab-btn" onclick="showTab('tab7',this)">💡 Conclusiones</button>
  </div>

  <div class="tab-panel">
    <div id="tab1" class="tab-content active">{tab1}</div>
    <div id="tab2" class="tab-content">{tab2}</div>
    <div id="tab3" class="tab-content">{tab3}</div>
    <div id="tab4" class="tab-content">{tab4}</div>
    <div id="tab5" class="tab-content">{tab5}</div>
    <div id="tab6" class="tab-content">{tab6}</div>
    <div id="tab7" class="tab-content">{tab7}</div>
  </div>

  <div class="footer">Reporte generado automáticamente · Cobre · {fecha}</div>
</div>

<script>
function showTab(id, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  // Redraw plotly charts inside this tab (needed after display:none → block)
  var plots = document.getElementById(id).querySelectorAll('.js-plotly-plot');
  plots.forEach(function(p) {{ Plotly.relayout(p, {{autosize: true}}); }});
}}
</script>
</body>
</html>
"""


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("⏳ Cargando datos desde HubSpot...", flush=True)
    df_contacts = load_campaign_data()
    if df_contacts.empty:
        print("❌ No se obtuvieron datos. Verifica HUBSPOT_API_KEY.")
        sys.exit(1)

    print(f"✅ {len(df_contacts)} contactos cargados.", flush=True)

    df_accounts = aggregate_to_accounts(df_contacts)
    df_kam      = get_kam_summary(df_contacts)
    seg_counts  = get_segment_counts(df_accounts)

    print("🔨 Construyendo HTML...", flush=True)

    fecha = datetime.now().strftime("%d %b %Y %H:%M")

    html = HTML_TEMPLATE.format(
        css=CSS,
        fecha=fecha,
        tab1=build_tab1(df_contacts, df_accounts, df_kam, seg_counts),
        tab2=build_tab2(df_contacts, df_accounts, df_kam),
        tab3=build_tab3(df_accounts),
        tab4=build_tab4(df_accounts, seg_counts),
        tab5=build_tab5(df_accounts),
        tab6=build_tab6(df_accounts),
        tab7=build_tab7(df_contacts, df_accounts, seg_counts),
    )

    out_path = Path(__file__).parent / "split_payments_reporte.html"
    out_path.write_text(html, encoding="utf-8")

    size_kb = out_path.stat().st_size // 1024
    print(f"✅ Listo: {out_path}  ({size_kb} KB)", flush=True)
    print("   Abre ese archivo en cualquier navegador para compartirlo.", flush=True)


if __name__ == "__main__":
    main()
