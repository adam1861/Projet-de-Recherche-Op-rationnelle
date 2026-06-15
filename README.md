# Simulateur Capacite-Commande - Maghreb Steel

Projet de Recherche Operationnelle : optimisation multi-commandes, multi-produits, multi-ressources pour le laminage a froid.

## Structure

```text
.
├── Donnees_MaghrebSteel.xlsx
├── main.py
├── app.py
├── rapport_technique.md
├── rapport_technique.pdf
├── requirements.txt
├── src/
│   ├── data_loader.py
│   ├── model.py
│   └── make_pdf.py
├── tests/
│   └── validate_solution.py
└── outputs/
    ├── base_resultats.xlsx
    ├── synthese_scenarios.xlsx
    └── fichiers CSV detailles
```

## Installation

```bash
python -m pip install -r requirements.txt
```

## Lancer toutes les resolutions

```bash
python main.py --data Donnees_MaghrebSteel.xlsx --out outputs --time-limit 300
```

Le script genere :

- solution de base,
- relaxation LP pour les shadow prices,
- modele avec campagnes binaires,
- scenario HRC +10 %,
- scenario panne LGB semaine 2,
- scenario commande urgente,
- enveloppe DC01,
- robustesse cadences +/-5 %.

## Valider la solution de base

```bash
python tests/validate_solution.py --data Donnees_MaghrebSteel.xlsx --decisions outputs/base_decisions.csv --out outputs/validation_base.csv
```

Resultat attendu :

```text
Toutes les contraintes controlees sont respectees
```

## Lancer l'application

```bash
streamlit run app.py
```

L'application permet de modifier le carnet de commandes, changer les hypotheses de scenario et relancer PuLP/CBC depuis une interface web locale.

## Regenerer le PDF du rapport

```bash
python -m src.make_pdf --md rapport_technique.md --pdf rapport_technique.pdf
```

## Resultats principaux

- Marge optimale de base : 33.21 MMAD apres correction du cout peinture PPGI et integration des stocks PK/interprocess.
- Taux de service : 78.78 %.
- Commandes acceptees : 50 / 66.
- Goulot machine principal : LGA/HDG semaine 1.
- Contraintes matiere critiques : HRC S320, DX51, DX52.

## Hypotheses importantes

- PuLP/CBC est utilise conformement a la consigne du projet.
- La contrainte ajoutee par image est integree : epaisseur < 0.6 mm sur LGA, epaisseur > 0.6 mm strictement sur LGB.
- Quarto est exclu du flux principal.
- PPGI reste exclusivement LGA ; donc les commandes PPGI d'epaisseur > 0.6 mm sont non routables dans ce cadrage.
- Le stock PK est modelise dynamiquement par grade. Les stocks interprocess FH-CRMA, FH-CRMB, BAF-out et SKP-out restent agreges, comme precise par Maghreb Steel, avec bornes min/max et cout de stockage.
