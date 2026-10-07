# Misses of `B_table_aware_bge_m3_vector` at recall@5: 3 of 24

Label each with one cause: table split badly, header lost, wrong year retrieved, wrong bank retrieved, number format mismatch, cross-lingual gap, question ambiguous, parse error, other.

## q013 [french, fr] bcge 2024
**Q:** Après avoir lu les autres informations du rapport annuel 2024 de la BCGE (hors états financiers audités), quelle remarque l’organe de révision a-t-il à formuler ?

**Evidence:** Nous n’avons aucune remarque à formuler à cet égard.
**Gold:** [('bcge', 2024, 121)]
> gold page 121: BCGE – Rapport de gestion 2024 / Rapport sur l’audit des comptes annuels Autres informations La responsabilité des autres informations incombe au conseil d’administration. Les autres informations comprennent les informations présentées dans le rapport annuel, à l’exception des comptes consolidés, des comptes annuels et de nos rapports correspondants. Notre opinion sur les comptes annuels ne s’éten
**Top hits:**
- bcge 2024 p44-44: Bank: BCGE | Year: 2024 | Section: 8.3 Honoraires supplémentaires (en CHF) Des honoraires supplémentaires de CHF 273'900 non liés à la révision ont été perçus en 2024 par une société du réseau Deloitte (CHF 385'000 en 20
- bcge 2025 p59-59: Bank: BCGE | Year: 2025 | Section: 8.3 Honoraires supplémentaires (en CHF) Des honoraires supplémentaires de CHF 268'500 non liés à la révision ont été perçus en 2025 par une société du réseau Deloitte (CHF 273'900 en 20
- bcge 2024 p43-44: Bank: BCGE | Year: 2024 | Section: 7.1 Obligation de présenter une offre 7.1 Obligation de présenter une offre Il n'existe aucune clause statutaire d'opting out ou d'opting up. 7.2 Clauses relatives aux prises de contrôl

**Cause:** 

## q070 [comparison, en] swissquote 2025
**Q:** For the 2025 financial year, which bank reported higher bottom-line earnings, Swissquote or Julius Baer, and by what amount in CHF millions?

**Evidence:** | Net profit of the period | | - | - | - | - | - | 366,392,439 | 366,392,439 | || | Net profit | - | 763.7 | - | - |
**Gold:** [('swissquote', 2025, 31), ('juliusbaer', 2025, 134)]
> gold page 31: Financial Report in CHF Notes Ordinary shares Share premium Share option reserve Other reserve Treasury shares Retained earnings Total BALANCE AS AT 1 JANUARY 3,065,634 61,744,388 8,551,758 (12,721,712) (73,221,169) 1,145,612,886 1,133,031,785 Net profit of the period – – – – – 366,392,439 366,392,439 Items that may be reclassified to the income statement – – – (1,568,424) – – (1,568,424) Items th
> gold page 134: Consolidated statement of changes in equity Share capital Retained earnings OCI related to equity instruments at FVOCI OCI related to debt instruments at FVOCI CHF m CHF m CHF m CHF m At 1 January 2024 4.1 7,106.1 95.9 -385.1 Net profit - 1,022.1 - - Items that may be reclassified to the income statement - - - 165.8 Items that will not be reclassified to the income statement - -23.9 -34.8 - Total 
**Top hits:**
- juliusbaer 2025 p206-206: Bank: Julius Baer | Year: 2025 | Section: Listed company that is consolidated | | Place of listing | Head Office | Currency | Share capital m | Capitalisation
- juliusbaer 2025 p209-209: Bank: Julius Baer | Year: 2025 | Section: Geographical information | | 31.12.2025 Non-current assets CHF m | 31.12.2024 CHF m | 2025 Operating income CHF m | 2024 CHF m | |-------------
- juliusbaer 2024 p210-210: Bank: Julius Baer | Year: 2024 | Section: Listed company that is consolidated | | Place of listing | Head Office | Currency | Share capital m | Capitalis

**Cause:** 

## q073 [table_lookup, en] swissquote 2024
**Q:** For Swissquote in fiscal year 2024, what was the aggregate remuneration expense reported for its board members and executive managers, in Swiss francs?

**Evidence:** | Total | 7,918,168 | 7,162,753 |
**Gold:** [('swissquote', 2024, 127)]
> gold page 127: NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS Section VII: Other notes to the consolidated financial statements Financial Report Related-party transactions Related-party transactions are defined as transactions and balances with members of the Board of Directors and of the Executive Management and their close family members (as defined by IAS 24), transactions with shareholders with a significant
**Top hits:**
- swissquote 2024 p204-205: Bank: Swissquote | Year: 2024 | Section: 2024 Board remuneration 2024 Board remuneration REMUNERATION REPORT 2024 Executive Management remuneration Fixed remuneration: CHF 1,269,138 Contributions and benefits: CHF 107,52
- swissquote 2024 p222-223: Bank: Swissquote | Year: 2024 | Section: 5 Reconciliation of remuneration with the approval of the General Meeting At the AGM of 8 May 2024, the shareholders approved a maximum aggregate remuneration for the Executive Ma
- swissquote 2024 p214-214: Bank: Swissquote | Year: 2024 | Section: 4 Remuneration for 2024 and external mandates | in CHF | Fixed remuneration - Cash

**Cause:** 
