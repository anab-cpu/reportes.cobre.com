"""
Clasifica cuentas en P1–P5 para la campaña PMM_Split Payments.
Replica la lógica de campaña-adopción-nequi/segmentation/ adaptada a este contexto.
"""
from __future__ import annotations

import pandas as pd

# ── Configuración de segmentos ────────────────────────────────────────────────

SEGMENTS: dict[str, dict] = {
    "P1": {
        "label":   "Hot Lead",
        "desc":    "Al menos un contacto abrió Y hizo clic",
        "color":   "#27AE60",
        "bg":      "#E8F8EE",
        "emoji":   "🔥",
        "action":  "Contactar KAM esta semana — máxima prioridad",
        "hs_list": False,  # Se maneja directo con KAM
    },
    "P2": {
        "label":   "Warm Lead",
        "desc":    "Todos los contactos abrieron, ninguno hizo clic",
        "color":   "#266D6C",
        "bg":      "#E4F0EF",
        "emoji":   "💙",
        "action":  "Enviar push email desde HubSpot",
        "hs_list": True,
    },
    "P3": {
        "label":   "Tibia",
        "desc":    "Algunos contactos abrieron (apertura parcial)",
        "color":   "#D4820A",
        "bg":      "#FEF3DC",
        "emoji":   "🟡",
        "action":  "Re-envío de campaña HubSpot",
        "hs_list": True,
    },
    "P4": {
        "label":   "Sin interacción",
        "desc":    "Ningún contacto abrió el correo",
        "color":   "#C0392B",
        "bg":      "#FDECEB",
        "emoji":   "❄️",
        "action":  "Contacto por WhatsApp vía KAM",
        "hs_list": False,
    },
    "P5": {
        "label":   "Bounce",
        "desc":    "Todos los contactos de la cuenta hicieron bounce",
        "color":   "#7F8C8D",
        "bg":      "#F2F3F4",
        "emoji":   "🚫",
        "action":  "Depurar / actualizar emails en base de datos",
        "hs_list": False,
    },
}


# ── Clasificación a nivel de cuenta ──────────────────────────────────────────

def _assign_segment(
    total: int,
    opened: int,
    clicked: int,
    bounced: int,
) -> str:
    if total == 0:
        return "P4"
    if bounced == total:
        return "P5"
    if clicked > 0:
        return "P1"
    if opened == total:
        return "P2"
    if opened > 0:
        return "P3"
    return "P4"


def aggregate_to_accounts(df_contacts: pd.DataFrame) -> pd.DataFrame:
    """
    Agrupa contactos por empresa y asigna segmento P1–P5.

    Input:  df de data_loader.load_campaign_data()
    Output: df con una fila por empresa + métricas + segment
    """
    if df_contacts.empty:
        return pd.DataFrame()

    rows: list[dict] = []

    for company_name, grp in df_contacts.groupby("company_name", dropna=False):
        n            = len(grp)
        opened_cnt   = int(grp["opened"].sum())
        clicked_cnt  = int(grp["clicked"].sum())
        bounced_cnt  = int(grp["bounced"].sum())
        kam          = grp["kam"].mode().iloc[0] if len(grp) > 0 else "Sin asignar"

        segment = _assign_segment(n, opened_cnt, clicked_cnt, bounced_cnt)

        contacts_list = []
        for _, c in grp.iterrows():
            name = f"{c.get('firstname', '')} {c.get('lastname', '')}".strip() or c.get("email", "")
            contacts_list.append({
                "contact_id":  c["contact_id"],
                "name":        name,
                "email":       c["email"],
                "jobtitle":    c.get("jobtitle", ""),
                "opened":      c["opened"],
                "clicked":     c["clicked"],
                "bounced":     c["bounced"],
                "open_count":  int(c.get("open_count", 1 if c["opened"] else 0)),
                "click_count": int(c.get("click_count", 1 if c["clicked"] else 0)),
                "open_ts":     c.get("open_ts", ""),
                "click_ts":    c.get("click_ts", ""),
            })

        total_opens  = int(grp["open_count"].sum()) if "open_count" in grp.columns else opened_cnt
        total_clicks = int(grp["click_count"].sum()) if "click_count" in grp.columns else clicked_cnt

        rows.append({
            "company_name":    str(company_name) if pd.notna(company_name) else "Sin empresa",
            "kam":             kam,
            "total_contacts":  n,
            "opened_count":    opened_cnt,
            "clicked_count":   clicked_cnt,
            "bounced_count":   bounced_cnt,
            "total_opens":     total_opens,   # incluye re-lecturas
            "total_clicks":    total_clicks,
            "open_rate":       round(opened_cnt / n, 4) if n > 0 else 0.0,
            "click_rate":      round(clicked_cnt / n, 4) if n > 0 else 0.0,
            "all_opened":      opened_cnt == n and n > 0,
            "any_clicked":     clicked_cnt > 0,
            "has_bounced":     bounced_cnt > 0,
            "segment":         segment,
            "contacts":        contacts_list,
            "contact_ids":     grp["contact_id"].tolist(),
        })

    df = pd.DataFrame(rows)

    # Orden de relevancia para mostrar
    seg_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3, "P5": 4}
    df["_seg_order"] = df["segment"].map(seg_order)
    df = df.sort_values(["_seg_order", "clicked_count", "opened_count"],
                        ascending=[True, False, False]).drop(columns=["_seg_order"])
    df = df.reset_index(drop=True)

    return df


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_kam_summary(df_contacts: pd.DataFrame) -> pd.DataFrame:
    """Métricas de envío y engagement por KAM."""
    rows = []
    for kam, grp in df_contacts.groupby("kam"):
        n = len(grp)
        rows.append({
            "KAM":              kam,
            "Contactos":        n,
            "Abrieron":         int(grp["opened"].sum()),
            "% Apertura":       round(grp["opened"].mean() * 100, 1),
            "Clicaron":         int(grp["clicked"].sum()),
            "% Clic":           round(grp["clicked"].mean() * 100, 1),
            "Bounces":          int(grp["bounced"].sum()),
            "Empresas":         grp["company_name"].nunique(),
        })
    return pd.DataFrame(rows).sort_values("% Apertura", ascending=False).reset_index(drop=True)


def get_segment_counts(df_accounts: pd.DataFrame) -> dict[str, int]:
    """Cuenta de empresas por segmento."""
    counts = df_accounts["segment"].value_counts().to_dict()
    return {p: counts.get(p, 0) for p in SEGMENTS}
