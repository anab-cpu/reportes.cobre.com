"""
Gestión de listas estáticas en HubSpot para segmentos P2 y P3.
Crea o actualiza una lista por segmento (opcionalmente filtrada por KAM).
"""
from __future__ import annotations

import os
import requests
from dotenv import load_dotenv

load_dotenv()

PORTAL_ID = "24140326"
LIST_PREFIX = "Split Payments"


def _headers() -> dict:
    key = os.getenv("HUBSPOT_API_KEY", "")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _find_list_by_name(name: str) -> str | None:
    resp = requests.get(
        "https://api.hubapi.com/contacts/v1/lists/all/lists/static",
        headers=_headers(),
        params={"count": 250},
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    for lst in resp.json().get("lists", []):
        if lst.get("name") == name:
            return str(lst["listId"])
    return None


def _create_static_list(name: str) -> str:
    resp = requests.post(
        "https://api.hubapi.com/contacts/v1/lists",
        headers=_headers(),
        json={"name": name, "dynamic": False},
        timeout=30,
    )
    resp.raise_for_status()
    return str(resp.json()["listId"])


def _add_contacts_to_list(list_id: str, contact_ids: list[str]) -> None:
    for i in range(0, len(contact_ids), 500):
        chunk = contact_ids[i : i + 500]
        resp = requests.post(
            f"https://api.hubapi.com/contacts/v1/lists/{list_id}/add",
            headers=_headers(),
            json={"vids": [int(c) for c in chunk]},
            timeout=30,
        )
        resp.raise_for_status()


def create_segment_list(
    segment: str,
    contact_ids: list[str],
    kam_filter: str | None = None,
) -> dict:
    """
    Crea o actualiza una lista estática para un segmento.

    Args:
        segment:     "P2" o "P3"
        contact_ids: IDs de contacto HubSpot a incluir
        kam_filter:  Si se pasa, la lista será específica por KAM

    Returns:
        dict con list_id, name, status, contacts_added, url
    """
    suffix = f" | {kam_filter}" if kam_filter else ""
    name = f"{LIST_PREFIX} | {segment}{suffix}"

    existing_id = _find_list_by_name(name)

    if existing_id:
        list_id = existing_id
        status = "actualizada"
    else:
        list_id = _create_static_list(name)
        status = "creada"

    if contact_ids:
        _add_contacts_to_list(list_id, contact_ids)

    return {
        "list_id":        list_id,
        "name":           name,
        "status":         status,
        "contacts_added": len(contact_ids),
        "url":            f"https://app.hubspot.com/contacts/{PORTAL_ID}/lists/{list_id}",
    }


def create_all_segment_lists(
    df_accounts,
    segments: list[str] | None = None,
    kam_filter: str | None = None,
) -> list[dict]:
    """
    Crea listas para todos los segmentos indicados.

    Args:
        df_accounts: DataFrame de segmentation.aggregate_to_accounts()
        segments:    Lista de segmentos a procesar (default: ["P2", "P3"])
        kam_filter:  Filtrar por KAM antes de crear las listas

    Returns:
        Lista de resultados por segmento
    """
    if segments is None:
        segments = ["P2", "P3"]

    df = df_accounts.copy()
    if kam_filter and kam_filter != "Todos":
        df = df[df["kam"] == kam_filter]

    results = []
    for seg in segments:
        df_seg = df[df["segment"] == seg]
        contact_ids = []
        for ids in df_seg["contact_ids"]:
            contact_ids.extend([str(i) for i in ids])

        if not contact_ids:
            results.append({
                "list_id":        None,
                "name":           f"{LIST_PREFIX} | {seg}" + (f" | {kam_filter}" if kam_filter else ""),
                "status":         "sin contactos",
                "contacts_added": 0,
                "url":            None,
            })
            continue

        result = create_segment_list(seg, contact_ids, kam_filter)
        results.append(result)

    return results
