# France Rémillard

Site marketing statique pour France Rémillard, courtière immobilière chez Royal LePage Humania (Saint-Jérôme).

## Lancer en local

Depuis ce dossier:

```bash
python -m http.server 8080
```

Ouvrir `http://localhost:8080`.

## Synchronisation des inscriptions

Les fiches viennent du flux public Royal LePage de l'agente (identifiant `53785`). Un script Python sans dépendance externe:

1. lit les pages du flux
2. télécharge les photos dans `assets/images/listings/`
3. écrit `data/listings.json`
4. génère `inscriptions/index.html` et une page par propriété
5. met à jour le bloc `<!-- SYNC:LISTINGS -->` de `index.html` et `sitemap.xml`

Lancer à la main:

```bash
python scripts/sync_listings.py
```

GitHub Actions (`.github/workflows/sync-listings.yml`) exécute le même script toutes les 6 heures, et sur demande via **Actions → Sync listings → Run workflow**. S'il y a un changement, le dépôt est mis à jour automatiquement.

Ne pas retirer les commentaires `SYNC:LISTINGS` dans `index.html`: le script s'arrête s'ils manquent.

## Contenu et conformité

- Couleurs officielles Royal LePage: rouge `#EA002A`, noir, blanc
- Photo officielle téléchargée depuis son profil Royal LePage
- Formulaire v1: `mailto:fremillard@royallepage.ca` (aucun CRM branché)
- Inscriptions: copies statiques synchronisées depuis Royal LePage, avec lien vers la fiche officielle
- Mentions OACIQ et nom du courtage dans le pied de page
- Distinctions officielles Royal LePage (médailles téléchargées de son profil)
- Aucune mention de frais ou de commission

## Déploiement GitHub Pages

1. Pousser la branche `main`
2. Settings → Pages → Source: `main` / racine
3. Quand le domaine de production est connu, remplacer le canonical `./` dans `index.html` et l'URL de `sitemap.xml`

Le workflow d'inscriptions pousse sur `main`. Si Pages est branché sur cette branche, le site se met à jour après chaque sync.

## Personnalisation plus tard

- Brancher un formulaire GoHighLevel à la place du `mailto`
- Ajouter une version anglaise
- Ajouter des témoignages seulement s'ils sont fournis
