"""
Carga datos de la campaña PMM_Split Payments usando la Email Events API de HubSpot.
Fuente de verdad: eventos reales (SENT, OPEN, CLICK, BOUNCE) por campaign ID.
"""
from __future__ import annotations

import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ── Campaign map: KAM → content_id → campaign_id ─────────────────────────────

CAMPAIGN_CONTENT_IDS: dict[str, str] = {
    "Manuela Osorio":    "210664433025",
    "Manuela Jaramillo": "210660108863",
    "Jose Carlos":       "210660109151",
    "Santiago Ramírez":  "210651260985",
    "Daniela Viuche":    "210655460137",
    "Marco Montaño":     "210655460104",
    "JP":                "210660082598",
    "Alberto Quintana":  "210660101812",
    "Angie Duque":       "210660109332",
}

# Resueltos una vez: content_id → campaign_id
_CAMPAIGN_IDS: dict[str, str] = {
    "Manuela Osorio":    "412787937",
    "Manuela Jaramillo": "412788681",
    "Jose Carlos":       "412788184",
    "Santiago Ramírez":  "412781494",
    "Daniela Viuche":    "412783955",
    "Marco Montaño":     "412782987",
    "JP":                "412787662",
    "Alberto Quintana":  "412784515",
    "Angie Duque":       "412786159",
}


def _headers() -> dict:
    key = os.getenv("HUBSPOT_API_KEY", "")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


# ── Events API ────────────────────────────────────────────────────────────────

def _fetch_events(campaign_id: str, event_type: str) -> list[dict]:
    """Descarga todos los eventos de un tipo para un campaign ID (paginado)."""
    events: list[dict] = []
    offset = None

    while True:
        params: dict = {
            "campaignId": campaign_id,
            "eventType":  event_type,
            "limit":      1000,
        }
        if offset:
            params["offset"] = offset

        resp = requests.get(
            "https://api.hubapi.com/email/public/v1/events",
            headers=_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        events.extend(data.get("events", []))

        if data.get("hasMore"):
            offset = data.get("offset")
        else:
            break

    return events


_BOT_CLICK_GAP_MS   = 5_000   # dos clicks del mismo email en < 5s = bot
_BOT_CLICK_DELAY_MS = 10_000  # click en < 10s desde el envío = bot


def _is_bot_click(click_timestamps: list[int], sent_ts: int | None = None) -> bool:
    """
    Devuelve True si el patrón de clicks corresponde a un escáner de seguridad.
    Criterios:
      1. Dos o más clicks del mismo destinatario con menos de 5s de diferencia.
      2. Un solo click que ocurrió en menos de 10s desde el envío.
    """
    if len(click_timestamps) >= 2:
        sorted_ts = sorted(click_timestamps)
        min_gap = min(sorted_ts[i+1] - sorted_ts[i] for i in range(len(sorted_ts)-1))
        if min_gap < _BOT_CLICK_GAP_MS:
            return True
    if len(click_timestamps) == 1 and sent_ts:
        if abs(click_timestamps[0] - sent_ts) < _BOT_CLICK_DELAY_MS:
            return True
    return False


def _fetch_all_events_for_kam(kam: str, campaign_id: str) -> dict[str, dict]:
    """
    Fetch SENT, OPEN, CLICK, BOUNCE para un KAM.
    Filtra bot-clicks (escáneres de seguridad corporativos).
    Retorna dict keyed by email con flags y conteos.
    """
    contacts: dict[str, dict] = {}

    # Recolectar todos los eventos primero
    raw_clicks: dict[str, list[int]] = {}   # email → lista de timestamps de click
    sent_ts_map: dict[str, int] = {}        # email → timestamp de SENT

    for event_type in ["SENT", "OPEN", "CLICK", "BOUNCE"]:
        events = _fetch_events(campaign_id, event_type)
        for e in events:
            email = (e.get("recipient") or "").lower().strip()
            if not email:
                continue
            if email not in contacts:
                contacts[email] = {
                    "email":       email,
                    "kam":         kam,
                    "sent":        False,
                    "opened":      False,
                    "clicked":     False,
                    "bounced":     False,
                    "open_count":  0,
                    "click_count": 0,
                    "open_ts":     "",
                    "click_ts":    "",
                }
            ts_raw = e.get("created", 0)
            ts = int(ts_raw) if ts_raw else 0

            if event_type == "SENT":
                contacts[email]["sent"] = True
                if ts:
                    sent_ts_map[email] = ts
            elif event_type == "OPEN":
                contacts[email]["open_count"] += 1
                ts_str = str(ts)
                if not contacts[email]["open_ts"] or ts_str < contacts[email]["open_ts"]:
                    contacts[email]["open_ts"] = ts_str
            elif event_type == "CLICK":
                raw_clicks.setdefault(email, []).append(ts)
                ts_str = str(ts)
                if not contacts[email]["click_ts"] or ts_str < contacts[email]["click_ts"]:
                    contacts[email]["click_ts"] = ts_str
            elif event_type == "BOUNCE":
                contacts[email]["bounced"] = True

    # Marcar opens (solo si hubo al menos un evento OPEN)
    for email, c in contacts.items():
        c["opened"] = c["open_count"] > 0

    # Marcar clicks filtrando bots
    for email, timestamps in raw_clicks.items():
        sent_ts = sent_ts_map.get(email)
        if not _is_bot_click(timestamps, sent_ts):
            contacts[email]["clicked"]     = True
            contacts[email]["click_count"] = len(timestamps)
        # Si es bot: clicked queda False, click_ts se limpia
        else:
            contacts[email]["click_ts"]    = ""
            contacts[email]["click_count"] = 0

    return contacts


# ── Enriquecimiento de contactos ──────────────────────────────────────────────

def _enrich_contacts(emails: list[str]) -> dict[str, dict]:
    """
    Batch-read de contactos por email → nombre, empresa, cargo, company_id.
    Retorna dict keyed by email (lowercase).
    """
    if not emails:
        return {}

    headers = _headers()
    enriched: dict[str, dict] = {}
    unique = list(set(e.lower().strip() for e in emails if e))

    # Paso 1: contactos por email
    contacts_by_id: dict[str, dict] = {}
    for i in range(0, len(unique), 100):
        chunk = unique[i : i + 100]
        payload = {
            "inputs":     [{"id": e} for e in chunk],
            "properties": ["email", "firstname", "lastname", "company",
                           "associatedcompanyid", "jobtitle", "phone"],
            "idProperty": "email",
        }
        resp = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts/batch/read",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if resp.status_code == 200:
            for c in resp.json().get("results", []):
                contacts_by_id[c["id"]] = c

    if not contacts_by_id:
        return {}

    # Paso 2: asociaciones contact → company
    cids = list(contacts_by_id.keys())
    for i in range(0, len(cids), 100):
        chunk = cids[i : i + 100]
        assoc_resp = requests.post(
            "https://api.hubapi.com/crm/v3/associations/contacts/companies/batch/read",
            headers=headers,
            json={"inputs": [{"id": c} for c in chunk]},
            timeout=30,
        )
        if assoc_resp.status_code == 200:
            for item in assoc_resp.json().get("results", []):
                cid = str(item.get("from", {}).get("id", ""))
                to_ids = [t["id"] for t in item.get("to", [])]
                if cid in contacts_by_id and to_ids:
                    contacts_by_id[cid]["company_id"] = str(to_ids[0])

    # Paso 3: nombres de empresa
    company_ids = list({
        c.get("company_id", c["properties"].get("associatedcompanyid", ""))
        for c in contacts_by_id.values()
        if c.get("company_id") or c["properties"].get("associatedcompanyid")
    })
    company_names: dict[str, str] = {}
    for i in range(0, len(company_ids), 100):
        chunk = [cid for cid in company_ids[i : i + 100] if cid]
        if not chunk:
            continue
        comp_resp = requests.post(
            "https://api.hubapi.com/crm/v3/objects/companies/batch/read",
            headers=headers,
            json={"inputs": [{"id": cid} for cid in chunk], "properties": ["name"]},
            timeout=30,
        )
        if comp_resp.status_code == 200:
            for comp in comp_resp.json().get("results", []):
                company_names[comp["id"]] = comp["properties"].get("name", "")

    # Construir dict final por email
    for cid, c in contacts_by_id.items():
        p = c["properties"]
        email = (p.get("email") or "").lower().strip()
        if not email:
            continue
        company_id = c.get("company_id") or p.get("associatedcompanyid") or ""
        enriched[email] = {
            "contact_id":   cid,
            "firstname":    p.get("firstname", ""),
            "lastname":     p.get("lastname", ""),
            "company":      p.get("company", ""),
            "company_id":   company_id,
            "company_name": company_names.get(str(company_id), "") or p.get("company", "") or "",
            "jobtitle":     p.get("jobtitle", ""),
            "phone":        p.get("phone", ""),
        }

    return enriched


# ── Pipeline principal ────────────────────────────────────────────────────────

def load_campaign_data() -> pd.DataFrame:
    """
    Pipeline completo usando Email Events API.
    Retorna un DataFrame con una fila por contacto y flags exactos de engagement.
    """
    all_rows: list[dict] = []

    for kam, campaign_id in _CAMPAIGN_IDS.items():
        contacts_events = _fetch_all_events_for_kam(kam, campaign_id)
        all_rows.extend(contacts_events.values())
        time.sleep(0.1)  # rate limit suave

    if not all_rows:
        return pd.DataFrame()

    df_events = pd.DataFrame(all_rows)

    # Enriquecer con datos del contacto
    all_emails = df_events["email"].tolist()
    enriched = _enrich_contacts(all_emails)

    # Merge: events + enrichment
    rows_final: list[dict] = []
    for _, row in df_events.iterrows():
        email = row["email"]
        info = enriched.get(email, {})

        firstname    = info.get("firstname", "")
        lastname     = info.get("lastname", "")
        company_name = (
            info.get("company_name")
            or info.get("company")
            or _guess_company_from_email(email)
        )

        rows_final.append({
            "contact_id":   info.get("contact_id", ""),
            "email":        email,
            "firstname":    firstname,
            "lastname":     lastname,
            "company":      info.get("company", ""),
            "company_id":   info.get("company_id", ""),
            "company_name": company_name,
            "jobtitle":     info.get("jobtitle", ""),
            "phone":        info.get("phone", ""),
            "kam":          row["kam"],
            "sent":         row.get("sent", False),
            "opened":       row.get("opened", False),
            "clicked":      row.get("clicked", False),
            "bounced":      row.get("bounced", False),
            "open_count":   int(row.get("open_count", 0)),
            "click_count":  int(row.get("click_count", 0)),
            "open_ts":      row.get("open_ts", ""),
            "click_ts":     row.get("click_ts", ""),
        })

    df = pd.DataFrame(rows_final)

    # Normalizar company_name vacíos
    df["company_name"] = df["company_name"].replace("", "Sin empresa").fillna("Sin empresa")

    return df


def _guess_company_from_email(email: str) -> str:
    """Extrae dominio como nombre tentativo de empresa si no hay datos en HubSpot."""
    try:
        domain = email.split("@")[1]
        return domain.split(".")[0].capitalize()
    except Exception:
        return "Sin empresa"
