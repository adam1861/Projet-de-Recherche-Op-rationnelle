# Rapport technique - Simulateur Capacite-Commande Maghreb Steel

## 1. Introduction

Le probleme consiste a construire un simulateur d'arbitrage industriel pour l'usine de laminage a froid de Tit Mellil. A partir d'un carnet de commandes, de capacites machines, de rendements, de couts, de stocks et d'arrets planifies, le simulateur decide quelles commandes livrer, sur quelle route metallurgique et a quelle semaine, en maximisant la marge sur cout variable.

Le modele traite rigoureusement CRC, HDG, PPGI et BACR, integre HRC DEC comme famille speciale via PK, et exclut Quarto du flux principal car cette famille ne suit pas le laminage a froid du perimetre projet.

Resultat de base : marge optimale 33.04 MMAD, 50 commandes acceptees sur 66, 13 551 T livrees sur 17 201 T, soit un taux de service de 78.78 %. Le solveur utilise est PuLP avec CBC.

## 2. Reponses de comprehension

**E1. Question business.** Le modele repond a la question : quelles commandes faut-il accepter et comment les inserer dans le plan de marche de 4 semaines pour maximiser la marge tout en respectant les contraintes industrielles. Ce n'est pas un simple calcul de cout, car il faut arbitrer entre commandes concurrentes sous ressources limitees.

**E2. Flux metallurgiques modelises.**

- HRC DEC : HRC -> PK -> HRC DEC.
- CRC : HRC -> PK -> CRMB -> BAF -> SKP -> CRC.
- HDG : HRC -> PK -> {CRMA ou CRMB} -> {LGA ou LGB} -> HDG.
- PPGI : HRC -> PK -> {CRMA ou CRMB} -> LGA -> PPGI.
- BACR voie A : HRC -> PK -> CRMB -> BAF -> LGB -> BACR.
- BACR voie B : HRC -> PK -> {CRMA ou CRMB} -> {LGA ou LGB} -> BACR.

Les branchements principaux sont le choix CRMA/CRMB et le choix LGA/LGB. Les confluences apparaissent lorsque plusieurs routes peuvent alimenter une meme famille finale, notamment HDG et BACR.

Contrainte additionnelle fournie en image : si l'epaisseur est inferieure a 0.6 mm, la ligne aval imposee est LGA ; si l'epaisseur est superieure a 0.6 mm, la ligne aval imposee est strictement LGB. Aucune commande du fichier n'a exactement 0.6 mm.

**E3. Familles et grades pressentis comme limitants.** Avant resolution, HDG semble critique par son tonnage eleve, 7 212 T. CRC est aussi contraint car il impose CRMB, BAF et SKP. Cote grades, S320 est suspect car la demande est de 1 935 T alors que la disponibilite HRC est seulement 800 T. DX51 est aussi tendu : 4 405 T demandes contre 3 200 T disponibles.

**E4. Trois leviers du planificateur.**

- Choisir les commandes a accepter ou refuser : variable de decision.
- Choisir les routes CRMA/CRMB et LGA/LGB : variable de decision.
- Decaler une livraison dans le temps avec penalite : variable de decision.

Les cadences, les arrets planifies, les prix HRC, les rendements et les stocks initiaux sont des parametres fixes dans le modele.

**B1. Question commerciale additionnelle.** Le directeur commercial voudrait savoir le prix minimal acceptable d'une nouvelle commande. On peut l'integrer en ajoutant une variable de prix ou en calculant, a partir du cout d'opportunite des ressources utilisees, le prix plancher tel que la marge nette de la commande soit positive apres consommation de HRC, capacites et penalites.

## 3. Formulation mathematique

### Ensembles et parametres

- I : commandes.
- R_i : routes admissibles de la commande i.
- T = {1,2,3,4} : semaines.
- L : lignes de production.
- F : familles produit.
- G : grades acier.
- q_i : tonnage de la commande i.
- p_i : prix de vente MAD/T.
- d_i : semaine demandee.
- rho_l : rendement de la ligne l.
- c_l(e_i) : cout variable de transformation de la ligne l selon l'epaisseur.
- HRC_g : disponibilite HRC du grade g.
- a_lfw : capacite nette de la ligne l pour la famille f en semaine w.

La capacite nette est :

```text
a_lfw = cadence_lf * (7 - arrets_lw)
```

### E5. Variables de decision

- x_i,r,p,d dans {0,1} : vaut 1 si la commande i est acceptee, produite par la route r en semaine p et livree en semaine d.
- z_l,f,w dans {0,1} en bonus campagnes : vaut 1 si la ligne l est ouverte en campagne famille f a la semaine w.
- Les variables de la relaxation LP sont identiques mais continues dans [0,1] pour obtenir shadow prices et couts reduits.

### E6. Fonction objectif

Le modele maximise :

```text
Somme_i,r,p,d x_i,r,p,d * Marge_i,r,p,d
```

Avec :

```text
Marge = Recette
      - Cout_HRC
      - Cout_transformation
      - Cout_zinc
      - Cout_peinture
      - Penalite_retard
      - Cout_stockage_fini
      + Valorisation_chutes
      + Valorisation_declasse
      + Valorisation_non_conforme
```

Chaque terme est en MAD. Les couts de transformation sont appliques au tonnage entrant de chaque process, donc corriges des rendements. Le HRC consomme pour une commande est le tonnage final divise par le produit des rendements de toute la route.

### E7. Contraintes de capacite

Pour chaque ligne l, famille f et semaine w :

```text
Somme des tonnages entrants sur l pour les commandes de famille f produites en w <= a_lfw
```

Les arrets planifies sont integres par la capacite nette. Exemple : LGA/HDG en semaine 1 a une capacite 250 * (7 - 1) = 1 500 T.

### E8. Bilans matiere et stocks

Pour une commande de tonnage final q_i sur une route r = (l1,...,lk), le tonnage entrant dans une ligne lm est :

```text
Input_i,r,lm = q_i / Produit_{n=m..k} rho_ln
```

Le stock produit fini de la famille f en fin de semaine w est :

```text
S_f,w = S_f,0
        + Somme_{i in f, r, p<=w, d} q_i x_i,r,p,d
        - Somme_{i in f, r, p, d<=w} q_i x_i,r,p,d
```

Et :

```text
S_min_f <= S_f,w <= S_max_f
```

Les stocks interprocess sont controles comme buffers statiques dans la validation, car le modele pedagogique ne separe pas les semaines par etape de process. L'extension complete consisterait a introduire des variables de production par etape et des delais entre PK, CRM, BAF/SKP et LGA/LGB.

### E9. Matiere premiere HRC

Pour chaque grade g :

```text
Somme_{i de grade g, r, p, d} HRC_input_i,r * x_i,r,p,d <= HRC_g
```

La consommation HRC depend de la route. Par exemple CRC consomme :

```text
q_i / (rho_PK * rho_CRMB * rho_BAF * rho_SKP)
```

### E10. Coherence dimensionnelle

- Les contraintes de capacite comparent des tonnes entrantes a des tonnes disponibles.
- Les contraintes HRC comparent des tonnes HRC consommees a des tonnes HRC disponibles.
- Les contraintes de stock comparent des tonnes a des bornes en tonnes.
- L'objectif additionne uniquement des MAD.

### B2. Retards

Le modele autorise d >= d_i. La penalite est :

```text
q_i * max(0, d - d_i) * penalite_priorite_i
```

Les penalites sont 500 MAD/T/semaine pour Haute, 200 pour Normale et 0 pour Basse.

### B3. Stockage

Le cout de stockage produit fini est :

```text
q_i * max(0, d - p) * 40 MAD/T/semaine
```

L'effet est de decourager les productions trop anticipees lorsqu'elles n'apportent pas assez de marge. Les buffers interprocess sont valorisables par une formulation etendue avec stocks par etape ; dans le code, ils sont controles en bornes comme buffers initiaux.

### B4. Campagnes

Avec campagnes binaires :

```text
Q_l,f,w <= a_l,f,w * z_l,f,w
Q_l,f,w >= 100 * z_l,f,w
Somme_f z_l,f,w <= 1
```

Cela evite les mini-batches et impose qu'une ligne ne soit pas dispersee sur trop de familles dans la meme semaine.

## 4. Implementation

**E11. Choix du solveur.** Le projet utilise PuLP, conforme a la consigne du professeur. PuLP est simple, lisible, adapte aux MILP de taille pedagogique, et embarque CBC. Pyomo serait plus puissant pour des modeles industriels plus modulaires, mais il est plus lourd a prendre en main. Gurobi serait plus rapide, mais necessite une licence.

**E12. Code.** Le depot contient :

- `main.py` : lance les resolutions et les scenarios.
- `src/data_loader.py` : lit l'Excel et nettoie les donnees.
- `src/model.py` : construit le modele PuLP, les routes, les couts et les exports.
- `tests/validate_solution.py` : validation independante.
- `app.py` : interface Streamlit.
- `outputs/` : resultats CSV/Excel.

Le modele de base a 1 020 variables et 188 contraintes. Le temps de resolution observe est 0.94 s pour la base, et environ 12.10 s pour le modele avec campagnes.

**E15. Validation.** Le script `tests/validate_solution.py` verifie les capacites, HRC, stocks, unicite des commandes et contrainte d'epaisseur. Resultat : toutes les contraintes controlees sont respectees.

## 5. Resultats

**E13. Solution optimale de base.**

- Statut : Optimal.
- Marge totale : 33.04 MMAD.
- Commandes acceptees : 50.
- Commandes refusees : 16.
- Tonnage livre : 13 551 T sur 17 201 T.
- Taux de service : 78.78 %.

**E14. Plan de marche.** Le plan complet est dans `outputs/base_capacity.csv` et `outputs/base_resultats.xlsx`. Les plus fortes utilisations sont :

- LGA/HDG semaine 1 : 1 449.7 T sur 1 500 T, soit 96.65 %.
- BAF/CRC semaine 1 : 1 029.4 T sur 1 260 T, soit 81.70 %.
- BAF/CRC semaine 2 : 956.3 T sur 1 260 T, soit 75.90 %.
- LGB/HDG semaine 1 : 2 365.3 T sur 3 185 T, soit 74.26 %.

**E16. Goulots.** Le principal goulot operationnel est LGA/HDG en semaine 1. Les contraintes matiere les plus fortes sont HRC S320, DX51 et DX52.

**E17. Commandes refusees et raisons.** Le fichier `outputs/base_refused_shadow_based.csv` liste les refus avec raison. Exemples :

- CMD-002 et CMD-014 : PPGI epaisseur 0.7, routage impossible car PPGI doit passer par LGA alors que la contrainte ajoutee impose LGB pour e > 0.6.
- CMD-005 : Quarto hors perimetre.
- CMD-009, CMD-030, CMD-031, CMD-032, CMD-058 : HRC DX51 rare.
- CMD-010, CMD-017, CMD-018, CMD-023, CMD-047, CMD-050, CMD-053 : HRC S320 rare.
- CMD-055 : HRC DX52 rare.

**E18. Shadow prices LP.** Les prix d'ombre utiles de la relaxation LP sont :

- HRC S320 : 1 974 MAD par tonne supplementaire.
- HRC DX51 : 1 752 MAD par tonne supplementaire.
- HRC DX52 : 1 454 MAD par tonne supplementaire.
- LGA/HDG semaine 1 : 472.5 MAD par tonne de capacite supplementaire.

Lecture business : une tonne additionnelle de HRC S320 a plus de valeur marginale qu'une tonne de capacite LGA/HDG. Le premier levier est donc l'approvisionnement matiere sur les grades tendus, avant l'investissement capacitaire court terme.

**E19. Marges par famille.**

- PPGI : 3 904 MAD/T.
- BACR : 2 456 MAD/T.
- HDG : 2 276 MAD/T.
- CRC : 1 959 MAD/T.
- HRC DEC : 454 MAD/T.

Le modele privilegie PPGI, BACR et HDG lorsque les routes sont possibles. CRC est plus souvent refuse car il consomme les grades rares et passe par le chemin long CRMB/BAF/SKP.

**B7. Commandes extremes.** La commande acceptee la plus rentable par tonne est CMD-006, PPGI DX51, 154 T, marge 4 238 MAD/T. La moins rentable acceptee est CMD-036, HRC DEC DC01, 475 T, marge 401 MAD/T. Elle est retenue car elle utilise surtout PK, une ressource tres peu saturee, et ne consomme pas les goulots aval LGA/LGB/BAF.

## 6. Analyse de sensibilite

**E20. HRC plus cher de 10 %.** La marge passe de 33.04 MMAD a 24.23 MMAD, soit -8.81 MMAD. Le taux de service baisse de 78.78 % a 76.02 %. L'estimation sans relance se fait par la consommation HRC du plan de base : l'effet attendu est approximativement la hausse de 10 % appliquee aux achats HRC consommes. La relance confirme une forte sensibilite a la matiere premiere.

**E21. Panne LGB de 2 jours supplementaires en semaine 2.** Impact observe : 0 MAD sur la marge et aucun changement de taux de service. La raison est que LGB en semaine 2 n'est pas sature dans la solution de base : l'utilisation reste sous la capacite meme apres deux jours d'arret supplementaires. Information maintenance : cette panne precise est absorbable ; une panne sur LGA semaine 1 serait beaucoup plus critique.

**E22. Commande urgente.** La commande urgente de 300 T HDG DC01, e = 0.5, largeur 1140, semaine 1, prix 11 500 MAD/T est acceptee. Elle passe par PK -> CRMB -> LGA et genere 1.067 MMAD de marge propre. Elle remplace CMD-036 dans le plan optimal. La marge globale augmente de 0.728 MMAD par rapport au cas de base ; l'acceptation est donc economiquement justifiee.

**B8. Enveloppe DC01.** La disponibilite DC01 a ete variee de -50 % a +50 %. La marge augmente jusqu'au niveau actuel de 6 750 T, puis reste plate au-dela. Le point de changement de pente est donc autour de 6 750 T : au-dessus, DC01 n'est plus le goulot et d'autres contraintes prennent le relais.

**B9. Robustesse cadences +/-5 %.** A -5 % de cadences, le plan reste resolvable avec le meme taux de service 78.78 %, mais la marge baisse legerement a 32.92 MMAD. A +5 %, la marge reste identique au cas de base, ce qui confirme que la disponibilite HRC, plus que la capacite machines, limite la valeur marginale.

**B5. Branch-and-Bound et relaxation.**

- Modele de base MILP : 222 noeuds CBC, 0.94 s, 33.04 MMAD.
- Relaxation LP base : 0.06 s, 33.33 MMAD.
- Modele campagnes MILP : 767 noeuds CBC, 12.10 s, 25.54 MMAD.
- Relaxation LP campagnes : 0.07 s, 32.65 MMAD.

Les campagnes rendent le probleme plus industriel mais plus restrictif : la marge baisse de 7.50 MMAD et le taux de service passe de 78.78 % a 60.17 %.

## 7. Recommandations strategiques

**E23. Trois recommandations.**

1. Securiser les approvisionnements HRC S320, DX51 et DX52. Les shadow prices indiquent que ces grades portent la plus forte valeur marginale.
2. Proteger LGA/HDG semaine 1, voire y ajouter de la capacite flexible, car c'est le goulot machine le plus visible.
3. Prioriser PPGI, BACR et HDG quand les routes sont admissibles ; refuser ou renegocier certaines commandes CRC faibles en marge, surtout sur grades rares.

**E24. Limites.**

- Les stocks interprocess ne sont pas dynamiques par etape et par semaine ; le modele suppose une synchronisation interne dans la meme semaine.
- Les largeurs et epaisseurs n'affectent pas les cadences au-dela des tranches de cout ; dans le reel, elles peuvent changer les vitesses et les reglages.
- Les campagnes sont modelisees par famille, pas par nuance, largeur, couleur ou sequence industrielle.
- Les contraintes financieres clients et risques credit sont exclues.
- Les commandes sont acceptees entieres ; un modele industriel pourrait autoriser des livraisons partielles contractuellement negociees.

## 8. Bonus et extension industrielle

**B6. Interface utilisateur.** L'application `app.py` est une interface Streamlit. Elle permet d'editer le carnet de commandes, changer le prix HRC, simuler un arret LGB, activer les campagnes et relancer PuLP sans modifier le code.

**B10. Feuille de route d'industrialisation.**

Pour passer du prototype a un outil de production, il faudrait ajouter :

- Connexion SI : ERP, carnet commercial, stocks reels, planning maintenance.
- Donnees industrielles fines : cadences par largeur/epaisseur, couleurs PPGI, contraintes de sequence, changements de cylindres, nettoyages, setups.
- Gestion des stocks interprocess dynamiques par etape.
- Gestion commerciale : priorites client, contrats, penalites reelles, risque credit.
- Interface robuste : authentification, historique des simulations, comparaison de scenarios, export planning.
- Supervision : logs, tests de non-regression, monitoring solveur.

Estimation d'industrialisation : en developpement interne, compter 2 a 3 ingenieurs pendant 12 a 18 mois. En prestation externe, budget de 800 000 a 1 500 000 MAD incluant developpement, integration SI et formation. Si le simulateur ameliore la marge de seulement 2 %, soit environ 750 000 MAD par horizon de 4 semaines sur une marge annuelle estimee a 150 MMAD, l'amortissement peut etre inferieur a 3 mois d'exploitation.

## 9. Conclusion

Le simulateur produit un plan optimal exploitable, chiffre les arbitrages et identifie les goulots. La solution de base livre 78.78 % du tonnage avec 33.04 MMAD de marge. Les ressources critiques ne sont pas seulement machines : les grades HRC S320, DX51 et DX52 expliquent une grande partie des refus. Le prototype est deja utilisable pour comparer des scenarios ; son passage en outil industriel demanderait surtout des donnees plus fines, une integration SI et une interface de pilotage robuste.
