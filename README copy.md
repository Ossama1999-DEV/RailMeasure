# RailMeasure — Mesure des distances sur les rails (Houston METRORail)

Application **Python + carte interactive** pour positionner autant de points que souhaité sur une voie ferroviaire, les déplacer manuellement et calculer la distance **le long de la voie** en **feet (ft)** entre chaque paire de points consécutifs.

## Démarrage

### Debian / Ubuntu / Linux

```bash
cd Houston_Track_Measure
python3 app.py
```

Ou `./lancer_linux.sh`. Un navigateur s'ouvre automatiquement à **http://127.0.0.1:8765/**. Pour désactiver l'ouverture automatique : `python3 app.py --no-browser`.

### Windows

Double-cliquer sur `lancer_windows.bat`, ou exécuter `py -3 app.py`.

**Prérequis :** Python 3.10+ ; **aucune installation pip**. Internet requis pour les données OpenStreetMap, la bibliothèque Leaflet (CDN) et les fonds cartographiques. Le serveur écoute uniquement sur `127.0.0.1`.

## Utilisation

1. Choisir **Houston Red Line** (relation OSM `1741729`), **Green Line** (`2728566`), ou saisir un identifiant de relation OSM.
2. Cliquer **Charger la voie**. Le téléchargement OSM peut prendre quelques dizaines de secondes. Les résultats sont mis en cache pendant 24 h dans `cache/`.
3. Choisir **N** dans « Nombre de points à créer », puis cliquer **Créer et répartir**. Les N points sont répartis sur une voie continue du réseau (heuristique : chemin le plus long approximatif, avec priorité au terminus Fannin South lorsqu'il est disponible).
4. **Glisser les points** pour les placer précisément devant un panneau, à un carrefour, sur un quai, etc. Ils sont repositionnés automatiquement sur le segment de rail le plus proche.
5. On peut aussi activer **Ajouter des points par clic sur la carte**, puis cliquer près des voies autant de fois que nécessaire ; cliquer sur un marqueur de station permet également d'ajouter un point à cet endroit.
6. Renommer les points dans le panneau latéral, les réordonner avec les flèches ou les supprimer.
7. Lire les distances **point 0 → point 1 → point 2 → …** et le total. Les distances sont en feet et en mètres.
8. Exporter les résultats en **CSV**, sauvegarder/restaurer un **projet JSON**, ou exporter les segments mesurés en **GeoJSON**.

### Importer une voie depuis QGIS

Si tu possèdes `Track.gpkg` ou d'autres données locales : dans QGIS, clic droit sur la couche des rails → **Exporter → Sauvegarder les entités sous… → GeoJSON**. Choisir le système de coordonnées **EPSG:4326 (WGS 84)**. Cliquer **+ GeoJSON** dans l'application. Les géométries `LineString` et `MultiLineString` sont prises en charge ; les `Point` nommés sont affichés comme stations. Le GeoJSON est importé **localement dans le navigateur**, sans transmission externe.

## Comment les distances sont calculées

- Chaque segment de rail OSM devient une arête d'un **graphe de voies**.
- Les marqueurs sont projetés sur les arêtes (pas sur le centre de la rue).
- Entre deux marqueurs, l'application calcule le **plus court chemin connecté** sur le graphe, en incluant les fractions de segment au départ et à l'arrivée.
- La longueur est la somme des distances géodésiques de chaque tronçon, puis convertie avec `1 m = 3.280839895 ft`.
- Si deux voies ne sont **pas connectées** dans les données, l'interface indique « Pas de voie connectée », au lieu d'inventer une distance.

**Important :** les distances sont calculées sur la **géométrie OpenStreetMap** ou le GeoJSON importé ; elles ne sont **pas des mesures topographiques certifiées**, ni nécessairement les chaînages `STA 1324+00` des plans METRO. Des voies parallèles, des aiguillages ou des erreurs de cartographie peuvent affecter le chemin choisi. Pour les PK du simulateur, vérifier avec les plans cotés et les points de référence connus. L'itinéraire le plus court ne garantit pas le parcours opérationnel d'un tramway.

## Tests (facultatifs)

```bash
python3 tests/test_server.py
node tests/test_graph.js
```

Le test JavaScript nécessite Node.js, mais **l'application n'en a pas besoin**.

## Structure

- `app.py` : serveur HTTP local Python, cache et téléchargement OSM.
- `railway.py` : lecture des relations OpenStreetMap et des stations (adapté du projet RailwayVisualizer).
- `web/index.html` : interface utilisateur.
- `web/style.css` : styles.
- `web/app.js` : carte, points, graphe, distances, import/export.
- `tests/` : tests hors ligne.

## Dépannage

- **Page blanche / carte absente :** vérifier la connexion Internet et l'accès à `unpkg.com` (Leaflet) et aux tuiles OSM.
- **Erreur lors du chargement OSM :** réessayer plus tard ; l'API OpenStreetMap peut être temporairement lente. Une voie GeoJSON importée depuis QGIS est une alternative.
- **Pas de voie connectée :** les deux points sont probablement sur des voies parallèles non reliées dans les données, ou sur des sections disjointes. Déplacer les points sur une même voie connectée.
- **Le port 8765 est utilisé :** `python3 app.py --port 8766`.
