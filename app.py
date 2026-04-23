"""Applikasjons-server inngangspunkt.

    python app.py

Starter Flask (REST + /ws/live),  åpner MQTT broen til megleren, og
laster restriksjons sonene fra luftrom-sone mocken (med en lokal
fallback hvis  mocken ikkje er  nåbar).
"""

from application_server.server import run


if __name__ == "__main__":
    run()
