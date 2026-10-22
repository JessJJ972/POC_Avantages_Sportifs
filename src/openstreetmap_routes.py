import json
import re
import threading
import time
import urllib.parse
import urllib.request

# Cache temporaire : aucune adresse enregistree sur disque.
_GEOCODE_CACHE = {}
_GEOCODE_LOCK = threading.Lock()
_DERNIER_APPEL_NOMINATIM = 0.0
_DELAI_NOMINATIM = 1.1


def route_distance_km(depart_lat, depart_lon, arrivee_lat, arrivee_lon, mode):
    """Calcule une distance pietonne ou cyclable avec Valhalla."""

    profils = {
        "walk": "pedestrian",
        "bike": "bicycle",
    }

    if mode not in profils:
        raise ValueError("Mode de deplacement non pris en charge")

    donnees = {
        "locations": [
            {"lat": float(depart_lat), "lon": float(depart_lon)},
            {"lat": float(arrivee_lat), "lon": float(arrivee_lon)},
        ],
        "costing": profils[mode],
        "units": "kilometers",
    }

    requete = urllib.request.Request(
        "https://valhalla1.openstreetmap.de/route",
        data=json.dumps(donnees).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "POC-Avantages-Sportifs-Demo/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(requete, timeout=25) as reponse:
        resultat = json.load(reponse)

    distance = float(resultat["trip"]["summary"]["length"])

    if distance <= 0:
        raise ValueError("Distance invalide")

    return distance

def geocode_address(address):
    """Geocode une adresse precise avec cache et limitation des requetes."""

    global _DERNIER_APPEL_NOMINATIM

    if not isinstance(address, str) or not address.strip():
        raise ValueError("Adresse manquante")

    adresse = " ".join(address.split())
    cle = adresse.casefold()

    # Le numero de rue doit etre present dans l'adresse demandee.
    numero_demande = re.match(r"^(\d+[a-zA-Z]?)\b", adresse)
    if numero_demande is None:
        raise ValueError("Adresse sans numero de rue")

    with _GEOCODE_LOCK:
        if cle in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cle]

        # Respecter au moins 1 seconde entre les appels Nominatim.
        attente = _DELAI_NOMINATIM - (
            time.monotonic() - _DERNIER_APPEL_NOMINATIM
        )
        if attente > 0:
            time.sleep(attente)

        params = urllib.parse.urlencode({
            "q": adresse,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
        })

        url = "https://nominatim.openstreetmap.org/search?" + params

        requete = urllib.request.Request(
            url,
            headers={
                "User-Agent": "POC-Avantages-Sportifs-Demo/1.0",
                "Accept": "application/json",
            },
        )

        # Comptabiliser l'appel meme si le serveur renvoie une erreur.
        _DERNIER_APPEL_NOMINATIM = time.monotonic()

        with urllib.request.urlopen(requete, timeout=20) as reponse:
            resultats = json.load(reponse)

        if not resultats:
            raise ValueError("Adresse introuvable")

        lieu = resultats[0]
        details = lieu.get("address", {})

        numero_trouve = str(details.get("house_number") or "").strip()

        if not numero_trouve:
            raise ValueError(
                "Adresse insuffisamment precise : numero de rue non confirme"
            )

        if numero_trouve.casefold() != numero_demande.group(1).casefold():
            raise ValueError(
                "Numero de rue different de celui demande"
            )

        coordonnees = (float(lieu["lat"]), float(lieu["lon"]))
        _GEOCODE_CACHE[cle] = coordonnees
        return coordonnees
