# Resell AI — MVP gratuit

Prototype local : produits -> analyse de marge -> génération d'annonces -> file de commandes.

Installation :
1. Python 3.11+
2. `python -m venv .venv`
3. Windows : `.venv\\Scripts\\activate` / macOS-Linux : `source .venv/bin/activate`
4. `pip install -r requirements.txt`
5. `streamlit run app.py`

Aucune clé API n'est nécessaire pour tester ce MVP.

Attention : ne pas utiliser de bots/scrapers sur les marketplaces quand leurs règles les interdisent. L'intégration eBay doit utiliser ses API officielles.
