# Rapport technique - Simulateur Capacite-Commande Maghreb Steel

## 1. Introduction

Maghreb Steel souhaite disposer d'un simulateur permettant d'arbitrer rapidement entre les commandes clients et les capacites disponibles de l'usine de laminage a froid de Tit Mellil. Le probleme est industriellement important car le carnet de commandes depasse volontairement la capacite disponible : il faut donc choisir les commandes qui creent le plus de valeur, tout en respectant les contraintes metallurgiques et operationnelles.

La question business centrale est la suivante : quelles commandes faut-il accepter, sur quelles routes les produire, et a quelle semaine les livrer afin de maximiser la marge sur cout variable de l'usine sur un horizon de quatre semaines ? Cette question est differente d'un simple calcul de cout, car le simulateur ne se contente pas d'evaluer une commande isolee. Il compare plusieurs commandes concurrentes, consomme des ressources rares, integre des penalites de retard, et mesure le cout d'opportunite d'utiliser une ligne ou un grade HRC pour une commande plutot qu'une autre.

Le perimetre principal du modele couvre les familles CRC, HDG, PPGI et BACR. La famille HRC DEC est traitee comme une famille speciale passant uniquement par PK. La famille Quarto est exclue du flux principal, car elle ne suit pas le circuit de laminage a froid considere dans le projet. Le carnet contient 66 commandes pour 17 201 T, dont 7 212 T de HDG, 4 991 T de CRC, 3 217 T de PPGI, 928 T de BACR, 610 T de HRC DEC et 243 T de Quarto.

Avant resolution, les familles les plus contraintes semblent etre HDG, a cause de son volume eleve et de son passage par LGA/LGB, et CRC, car elle impose le chemin complet PK -> CRMB -> BAF -> SKP. Les grades probablement limitants sont S320, avec 1 935 T demandees pour seulement 800 T disponibles, et DX51, avec 4 405 T demandees pour 3 200 T disponibles.

Les leviers principaux du planificateur sont : choisir les commandes a accepter ou refuser, choisir la route industrielle admissible, et decaler certaines livraisons avec penalite. Ces trois leviers sont modelises comme variables de decision. Les cadences, les rendements, les prix HRC, les arrets planifies et les stocks initiaux sont consideres comme des parametres.

Le modele integre aussi la contrainte supplementaire donnee oralement puis en image : une commande d'epaisseur strictement inferieure a 0.6 mm doit passer par LGA, tandis qu'une commande d'epaisseur strictement superieure a 0.6 mm doit passer par LGB. Aucune commande du fichier n'a une epaisseur exactement egale a 0.6 mm.

Objectifs du simulateur :

- maximiser la marge industrielle ;
- respecter les capacites, les rendements, les arrets planifies, les stocks et la disponibilite HRC ;
- identifier les commandes refusees et les contraintes bloquantes ;
- produire un plan de marche lisible par ligne, famille et semaine ;
- permettre des analyses de sensibilite pour aider la decision.

Bonus B1 : du point de vue du directeur commercial, une question additionnelle utile serait de determiner le prix minimal acceptable d'une nouvelle commande. Cette extension peut etre integree en calculant le cout d'opportunite des ressources consommees par la commande : HRC, capacites machines, stockage et retard. Le prix plancher est alors le prix qui rend la marge nette non negative apres prise en compte de ces couts d'opportunite.

## 2. Formulation

### 2.1 Flux metallurgiques

Les routes industrielles modelisees sont :

- HRC DEC : HRC -> PK -> HRC DEC.
- CRC : HRC -> PK -> CRMB -> BAF -> SKP -> CRC.
- HDG : HRC -> PK -> {CRMA ou CRMB} -> {LGA ou LGB} -> HDG.
- PPGI : HRC -> PK -> {CRMA ou CRMB} -> LGA -> PPGI.
- BACR voie A : HRC -> PK -> CRMB -> BAF -> LGB -> BACR.
- BACR voie B : HRC -> PK -> {CRMA ou CRMB} -> {LGA ou LGB} -> BACR.

Les points de branchement sont le choix CRMA/CRMB, le choix LGA/LGB, et pour BACR le choix entre voie A via BAF et voie B directe. Les points de confluence apparaissent lorsque plusieurs routes peuvent alimenter une meme famille finale, notamment HDG et BACR.

La contrainte d'epaisseur modifie les routes admissibles :

- si e_i < 0.6, alors la ligne aval doit etre LGA ;
- si e_i > 0.6, alors la ligne aval doit etre LGB ;
- PPGI etant exclusivement LGA dans le cadrage du projet, les commandes PPGI avec e_i > 0.6 deviennent non routables.

### 2.2 Ensembles

- I : ensemble des commandes.
- T = {1,2,3,4} : semaines de l'horizon.
- L : lignes de production, avec L = {PK, CRMA, CRMB, BAF, SKP, LGA, LGB}.
- F : familles de produits.
- G : grades d'acier.
- R_i : routes admissibles de la commande i.

### 2.3 Parametres

- q_i : tonnage de la commande i, en tonnes.
- p_i : prix de vente de la commande i, en MAD/T.
- d_i : semaine de livraison demandee.
- g_i : grade de la commande.
- e_i : epaisseur de la commande.
- rho_l : rendement de la ligne l.
- alpha_l : taux de chutes de la ligne l.
- beta_l : taux de declasse de la ligne l.
- gamma_l : taux de non-conforme de la ligne l.
- c_l(e_i) : cout variable de transformation de la ligne l pour l'epaisseur e_i.
- h_g,wid : prix HRC du grade g et de la largeur consideree.
- H_g : disponibilite HRC du grade g sur l'horizon.
- cad_l,f : cadence journaliere de la ligne l pour la famille f.
- arret_l,t : nombre de jours d'arret planifie de la ligne l en semaine t.
- S0_f : stock initial de produit fini de la famille f.
- Smin_f, Smax_f : bornes de stock de produit fini.

La capacite nette est :

```text
A_l,f,t = cad_l,f * (7 - arret_l,t)
```

### 2.4 Variables de decision

Variable principale :

```text
x_i,r,p,d ∈ {0,1}
```

Elle vaut 1 si la commande i est acceptee, produite selon la route r, en semaine de production p, et livree en semaine d. Elle vaut 0 sinon.

Pour le bonus campagnes :

```text
z_l,f,t ∈ {0,1}
```

Elle vaut 1 si la ligne l est ouverte pour une campagne de famille f en semaine t.

Pour obtenir les shadow prices et couts reduits, on resout aussi la relaxation lineaire :

```text
0 <= x_i,r,p,d <= 1
0 <= z_l,f,t <= 1
```

### 2.5 Fonction objectif

Le modele maximise la marge totale :

```text
Max Z = Somme_i,r,p,d x_i,r,p,d * M_i,r,p,d
```

La marge d'une option commande-route-semaine est :

```text
M_i,r,p,d =
  Recette_i
  - Cout_HRC_i,r
  - Cout_transformation_i,r
  - Cout_zinc_i,r
  - Cout_peinture_i,r
  - Penalite_retard_i,d
  - Cout_stockage_fini_i,p,d
  + Valorisation_chutes_i,r
  + Valorisation_declasse_i,r
  + Valorisation_non_conforme_i,r
```

La recette est :

```text
Recette_i = q_i * p_i
```

Pour une route r = (l1,...,lk), le tonnage entrant dans la ligne lm est :

```text
Input_i,r,lm = q_i / Produit_{n=m..k} rho_ln
```

La consommation HRC est donc :

```text
HRCInput_i,r = q_i / Produit_{l∈r} rho_l
```

Le cout HRC est :

```text
Cout_HRC_i,r = HRCInput_i,r * h_g_i,width_i
```

Le cout de transformation est :

```text
Cout_transformation_i,r = Somme_l∈r Input_i,r,l * c_l(e_i)
```

La valorisation des chutes est :

```text
Valorisation_chutes_i,r =
Somme_l∈r Input_i,r,l * alpha_l * prix_chutes
```

Le declasse et le non-conforme sont valorises comme fractions du prix de vente conforme :

```text
Valorisation_declasse_i,r =
Somme_l∈r Input_i,r,l * beta_l * coef_declasse * p_i
```

```text
Valorisation_non_conforme_i,r =
Somme_l∈r Input_i,r,l * gamma_l * coef_non_conforme * p_i
```

Pour HDG et PPGI, le cout zinc est :

```text
Cout_zinc_i = q_i * conso_zinc * prix_zinc
```

Pour PPGI, le cout peinture est :

```text
Cout_peinture_i = q_i * conso_peinture * prix_peinture
```

### 2.6 Contraintes

Unicite d'acceptation :

```text
Somme_r,p,d x_i,r,p,d <= 1       pour toute commande i
```

Une commande peut etre acceptee une seule fois, sur une seule route, une seule semaine de production et une seule semaine de livraison.

Contrainte de temps :

```text
p <= d
```

On ne peut pas livrer une commande avant sa production.

Retard avec penalite, bonus B2 :

```text
retard_i,d = max(0, d - d_i)
Penalite_retard_i,d = q_i * retard_i,d * penalite_priorite_i
```

Capacites :

```text
Somme_{i,r,p,d : p=t, l∈r, famille_i=f}
Input_i,r,l * x_i,r,p,d
<= A_l,f,t
```

Cette contrainte est ecrite pour chaque ligne l, famille f et semaine t.

Matiere premiere HRC :

```text
Somme_{i,r,p,d : g_i=g}
HRCInput_i,r * x_i,r,p,d
<= H_g
```

Stocks de produits finis :

```text
S_f,t = S0_f
      + Somme_{i∈f,r,p,d : p<=t} q_i x_i,r,p,d
      - Somme_{i∈f,r,p,d : d<=t} q_i x_i,r,p,d
```

```text
Smin_f <= S_f,t <= Smax_f
```

Stockage, bonus B3 :

```text
Cout_stockage_fini_i,p,d =
q_i * max(0, d - p) * cout_stockage_fini
```

Les stocks interprocess sont controles comme buffers statiques dans la validation. Une version industrielle complete introduirait des variables de stock par etape et par semaine.

Routage par epaisseur :

```text
Si e_i < 0.6, alors x_i,r,p,d = 0 pour toute route r contenant LGB
```

```text
Si e_i > 0.6, alors x_i,r,p,d = 0 pour toute route r contenant LGA
```

Routage PPGI :

```text
PPGI passe uniquement par LGA
```

Donc une commande PPGI d'epaisseur superieure a 0.6 est non routable dans ce cadrage.

Campagnes, bonus B4 :

```text
Q_l,f,t <= A_l,f,t * z_l,f,t
```

```text
Q_l,f,t >= 100 * z_l,f,t
```

```text
Somme_f z_l,f,t <= 1
```

Cette extension evite les mini-batches non economiques et force une ligne a se concentrer sur une famille par semaine.

### 2.7 Coherence dimensionnelle

Les contraintes de capacite comparent des tonnes entrantes a des tonnes de capacite. Les contraintes HRC comparent des tonnes HRC consommees a des tonnes HRC disponibles. Les contraintes de stock comparent des tonnes a des bornes en tonnes. La fonction objectif additionne uniquement des montants en MAD. Il n'y a donc pas de melange du type tonnes <= MAD.

## 3. Implementation

Le projet est implemente en Python avec PuLP, conformement a la consigne du professeur. Le solveur utilise est CBC, fourni avec PuLP.

PuLP a ete retenu car il est simple a lire, adapte aux programmes lineaires mixtes en nombres entiers, facile a installer, et suffisant pour la taille du probleme. Pyomo serait plus puissant pour une industrialisation lourde, mais plus complexe a prendre en main. Gurobi serait plus rapide sur de tres grands modeles, mais impose une licence.

Architecture du code :

- `main.py` lance la resolution de base, les scenarios et les exports.
- `src/data_loader.py` lit les onglets Excel, nettoie les libelles et construit les dictionnaires de donnees.
- `src/model.py` genere les routes admissibles, calcule les couts, construit le modele PuLP, resout et exporte les resultats.
- `tests/validate_solution.py` verifie la solution sans utiliser le solveur.
- `app.py` fournit une interface Streamlit pour un utilisateur non technique.
- `outputs/` contient les fichiers CSV et Excel generes.

Le code lit directement `Donnees_MaghrebSteel.xlsx`, construit les options admissibles commande-route-semaine, resout le programme lineaire mixte, puis exporte les resultats dans `outputs/base_resultats.xlsx` et dans plusieurs CSV.

Le modele de base contient 1 020 variables et 188 contraintes. Il est resolu en 0.94 seconde. Le modele avec campagnes contient 1 100 variables et 296 contraintes. Il est resolu en 12.10 secondes.

La relaxation LP est aussi resolue pour obtenir les shadow prices et les couts reduits. Cette relaxation est necessaire pour interpreter les contraintes saturantes, car les prix d'ombre d'un MILP entier ne sont pas directement interpretables comme dans un programme lineaire.

Validation E15 : le script de validation controle l'unicite des commandes, les routages, la contrainte d'epaisseur, les capacites, la disponibilite HRC et les bornes de stock. Le resultat obtenu est :

```text
Toutes les contraintes controlees sont respectees
```

Bonus B5 : comparaison MILP et relaxation :

- modele de base MILP : 222 noeuds CBC, 0.94 seconde, marge 33.04 MMAD ;
- relaxation LP base : 0.06 seconde, marge 33.33 MMAD ;
- modele campagnes MILP : 767 noeuds CBC, 12.10 secondes, marge 25.54 MMAD ;
- relaxation LP campagnes : 0.07 seconde, marge 32.65 MMAD.

Bonus B6 : l'application Streamlit permet d'editer le carnet, modifier le prix HRC, simuler un arret LGB, activer les campagnes binaires, lancer le solveur et visualiser le plan, les goulots, les commandes et la consommation HRC.

## 4. Resultats

La solution optimale de base donne :

- statut : Optimal ;
- marge totale : 33.04 MMAD ;
- commandes acceptees : 50 sur 66 ;
- commandes refusees : 16 ;
- tonnage livre : 13 551 T sur 17 201 T ;
- taux de service global : 78.78 %.

Le plan de marche detaille est exporte dans `outputs/base_capacity.csv` et `outputs/base_resultats.xlsx`. Les principales utilisations de lignes sont :

- LGA/HDG semaine 1 : 1 449.7 T sur 1 500 T, soit 96.65 % ;
- BAF/CRC semaine 1 : 1 029.4 T sur 1 260 T, soit 81.70 % ;
- BAF/CRC semaine 2 : 956.3 T sur 1 260 T, soit 75.90 % ;
- LGB/HDG semaine 1 : 2 365.3 T sur 3 185 T, soit 74.26 % ;
- CRMB/HDG semaine 1 : 3 933.0 T sur 5 523 T, soit 71.21 %.

Le principal goulot machine est donc LGA pour HDG en semaine 1. Les lignes PK, CRMA et plusieurs capacites LGB restent globalement moins saturees.

Consommation HRC par grade :

- DC01 : 6 610.7 T utilisees sur 6 750 T, soit 97.94 % ;
- DD13 : 2 828.2 T sur 3 750 T, soit 75.42 % ;
- DX51 : 3 185.7 T sur 3 200 T, soit 99.55 % ;
- DX52 : 1 458.0 T sur 1 500 T, soit 97.20 % ;
- S320 : 725.2 T sur 800 T, soit 90.65 %.

Les shadow prices issus de la relaxation LP indiquent les ressources les plus critiques :

- HRC S320 : 1 974 MAD par tonne supplementaire ;
- HRC DX51 : 1 752 MAD par tonne supplementaire ;
- HRC DX52 : 1 454 MAD par tonne supplementaire ;
- LGA/HDG semaine 1 : 472.5 MAD par tonne de capacite supplementaire.

L'interpretation business est claire : une tonne additionnelle de HRC S320, DX51 ou DX52 apporte plus de valeur marginale qu'une tonne additionnelle de capacite LGA/HDG. La matiere premiere est donc un levier prioritaire.

Commandes refusees :

- CMD-002 et CMD-014 : PPGI d'epaisseur 0.7, non routables car PPGI impose LGA alors que la contrainte ajoutee impose LGB pour e > 0.6 ;
- CMD-005 : Quarto hors perimetre ;
- plusieurs commandes CRC DX51 ou S320 : refusees a cause de la rarete HRC et d'une marge inferieure aux commandes retenues ;
- CMD-055 : refusee car DX52 est rare.

Le fichier `outputs/base_refused_shadow_based.csv` contient la liste complete des commandes refusees avec raison tracee a partir de la relaxation LP.

Marge moyenne par famille :

- PPGI : 3 904 MAD/T ;
- BACR : 2 456 MAD/T ;
- HDG : 2 276 MAD/T ;
- CRC : 1 959 MAD/T ;
- HRC DEC : 454 MAD/T.

Le modele privilegie donc PPGI, BACR et HDG lorsque les routes sont admissibles. CRC est plus souvent refuse car il utilise un chemin long et consomme des grades HRC critiques.

Bonus B7 : la commande acceptee la plus rentable par tonne est CMD-006, PPGI DX51, avec une marge de 4 238 MAD/T. La moins rentable acceptee est CMD-036, HRC DEC DC01, avec 401 MAD/T. Elle est tout de meme retenue car elle consomme principalement PK, qui n'est pas un goulot dans la solution.

## 5. Analyse de sensibilite

Scenario E20 : hausse de 10 % du prix HRC.

La marge passe de 33.04 MMAD a 24.23 MMAD, soit une baisse de 8.81 MMAD. Le taux de service passe de 78.78 % a 76.02 %. Avant relance, l'impact peut etre estime en appliquant la hausse de 10 % a la consommation HRC du plan de base. La relance confirme que le modele est tres sensible au cout de la matiere premiere.

Interpretation business : la negociation HRC est un levier majeur. Une hausse HRC deteriore fortement la marge et conduit le modele a refuser davantage de commandes.

Scenario E21 : panne LGB de deux jours supplementaires en semaine 2.

La marge reste identique a 33.04 MMAD et le taux de service reste a 78.78 %. Aucune commande ne bascule. Cela s'explique par le fait que LGB semaine 2 n'est pas saturee dans la solution de base. La capacite residuelle permet d'absorber cette panne.

Interpretation business : cette panne precise est peu critique. En revanche, une panne sur LGA semaine 1 serait beaucoup plus dangereuse, car LGA/HDG semaine 1 est presque saturee.

Scenario E22 : commande urgente entrante.

La commande urgente de 300 T de HDG DC01, epaisseur 0.5 mm, largeur 1140 mm, semaine 1, prix 11 500 MAD/T, est acceptee. Elle passe par PK -> CRMB -> LGA. Sa marge propre est de 1.067 MMAD. Elle remplace CMD-036 dans le plan optimal.

La marge globale passe de 33.04 MMAD a 33.77 MMAD, soit un gain de 0.728 MMAD. Le taux de service global baisse mecaniquement car le carnet total augmente de 300 T, mais economiquement l'acceptation est rentable.

Bonus B8 : enveloppe DC01.

La disponibilite DC01 a ete variee de -50 % a +50 %. La marge augmente jusqu'a la disponibilite actuelle de 6 750 T, puis reste stable au-dela. Le changement de pente se situe donc autour de 6 750 T. Cela signifie qu'une fois ce niveau atteint, DC01 cesse d'etre le goulot marginal et d'autres contraintes prennent le relais.

Bonus B9 : robustesse aux cadences incertaines de +/-5 %.

A -5 % de cadences, le modele reste faisable avec le meme taux de service de 78.78 %, mais la marge baisse legerement a 32.92 MMAD. A +5 %, la marge reste identique au cas de base. Cette analyse confirme que le plan est relativement robuste aux petites variations de cadence, et que le facteur limitant principal est plutot la disponibilite HRC.

## 6. Limites et extensions

Le modele reste une version pedagogique d'un probleme industriel plus riche.

Premiere limite : les stocks interprocess ne sont pas dynamiques par etape et par semaine. Le modele verifie les buffers, mais ne decrit pas explicitement les flux semaine par semaine entre PK, CRM, BAF, SKP et LGA/LGB. Une extension industrielle devrait introduire des variables de production par etape, des stocks intermediaires dynamiques et des delais de passage.

Deuxieme limite : les cadences sont agragees par ligne et famille. Dans la realite, elles dependent plus finement de l'epaisseur, de la largeur, de la nuance, de la qualite de surface et des reglages.

Troisieme limite : les campagnes sont modelisees par famille uniquement. Un vrai planning devrait tenir compte des sequences, changements de cylindres, nettoyages, couleurs PPGI, largeurs compatibles, contraintes de bobines et tailles minimales par lot.

Quatrieme limite : les contraintes commerciales et financieres clients ne sont pas incluses. Le modele suppose que toutes les commandes sont eligibles financierement, alors qu'un outil industriel devrait integrer plafonds clients, encours, conditions de paiement et risque credit.

Cinquieme limite : les commandes sont acceptees entieres ou refusees. En pratique, certaines commandes pourraient etre livrees partiellement, fractionnees ou renegociees.

Bonus B10 : feuille de route d'industrialisation.

Pour transformer le prototype en outil de production, il faudrait ajouter :

- connexion ERP et SI commercial ;
- recuperation automatique des stocks reels, arrets, capacites et carnet ;
- modelisation fine des stocks interprocess ;
- cadences par epaisseur, largeur, nuance et gamme ;
- contraintes de sequence et de campagnes reelles ;
- gestion des couleurs et peintures PPGI ;
- simulation multi-horizon, par exemple 8 a 12 semaines ;
- interface utilisateur robuste avec historique des simulations ;
- comparaison automatique de scenarios ;
- droits utilisateurs, logs, tests de non-regression et supervision solveur.

Estimation d'industrialisation : en developpement interne, il faut compter 2 a 3 ingenieurs pendant 12 a 18 mois. En prestation externe, le budget probable est de 800 000 a 1 500 000 MAD, incluant developpement, integration SI et formation. Si le simulateur ameliore la marge de seulement 2 %, soit environ 750 000 MAD par horizon de 4 semaines sur une marge annuelle estimee a 150 MMAD, l'amortissement peut etre inferieur a 3 mois d'exploitation.

## 7. Conclusion

Le simulateur construit avec PuLP fournit un plan de marche optimal et interpretable pour le carnet Maghreb Steel. La solution de base livre 13 551 T, soit 78.78 % du tonnage demande, avec une marge de 33.04 MMAD. Le modele identifie les commandes non planifiables, les goulots machines et les grades HRC critiques.

Les recommandations principales sont :

1. securiser les approvisionnements HRC S320, DX51 et DX52, car leurs shadow prices sont les plus eleves ;
2. proteger la capacite LGA/HDG en semaine 1, qui est le principal goulot machine ;
3. prioriser les commandes PPGI, BACR et HDG lorsque leur route est admissible, et renegocier ou refuser certaines commandes CRC de faible marge sur grades rares.

Le prototype repond aux objectifs du projet : formulation mathematique, implementation PuLP, resultats optimaux, validation independante, scenarios de sensibilite, bonus campagnes, interface Streamlit et feuille de route d'industrialisation. Pour un usage industriel regulier, l'effort principal porterait sur la finesse des donnees, l'integration SI et l'enrichissement des contraintes de planning reel.
