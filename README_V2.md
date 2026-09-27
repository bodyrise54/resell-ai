# Resell AI V2 — moteur automatique

Cette version ajoute un **worker automatique** et un **GitHub Actions scheduler**.

## Ce que fait cette version

Chaque jour, GitHub Actions :
1. lit le catalogue autorisé présent dans `products.csv`;
2. calcule un prix cible;
3. élimine les produits sans stock;
4. classe les produits;
5. garde jusqu'à 60 produits;
6. génère `selected_products.csv`;
7. génère `draft_listings.csv`.

Le dépôt peut donc fonctionner sans laisser Streamlit ouvert.

## Important

Le catalogue de démonstration est volontairement local. Il ne scrape pas Temu, SHEIN, Vinted, Leboncoin ou eBay.

Pour passer au vrai système :
- remplacer `products.csv` par une source fournisseur/API/catalogue autorisée;
- connecter ensuite l'API eBay;
- ajouter les contrôles de conformité, stock, prix et images;
- ajouter le traitement des commandes avec une intégration fournisseur autorisée.

Le mode de publication eBay doit rester désactivé tant que les identifiants/API et les paramètres de vente ne sont pas configurés.

## Lancer manuellement

Dans GitHub :
Actions → Resell AI - daily product selection → Run workflow.

## Changer la fréquence

Le fichier `.github/workflows/daily-resell.yml` utilise actuellement :
`0 8 * * *`

Cela correspond à une exécution quotidienne à 08:00 UTC. Les exécutions planifiées de GitHub peuvent être retardées.

## Étape suivante

Après validation du moteur, brancher :
Source fournisseur/API → filtre → top 60 → générateur d'annonce → eBay Inventory API → suivi prix/stock → commandes.

Ne mets jamais de clé API ou de mot de passe dans `products.csv`, le code ou les messages GitHub. Les secrets devront être stockés dans GitHub Secrets.
